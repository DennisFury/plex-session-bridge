from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.apple_tv import AppleTvClient
from app.config import BridgeConfig, DeviceConfig
from app.models import (
    DeviceRuntimeState,
    DevicePowerState,
    Decision,
    PlaybackState,
    PlexMediaIdentity,
    ReconcileResult,
    Registration,
    SyntheticSession,
)
from app.plex import PlexClient, PlexSessionSnapshot
from app.registrations import RegistrationStore


LOG = logging.getLogger(__name__)


class Reconciler:
    def __init__(
        self,
        config: BridgeConfig,
        apple_tv: AppleTvClient | None = None,
        plex: PlexClient | None = None,
        registrations: RegistrationStore | None = None,
    ) -> None:
        self.config = config
        self.apple_tv = apple_tv or AppleTvClient()
        self.plex = plex or PlexClient(config.plex.url, config.plex.token)
        self.registrations = registrations or RegistrationStore()
        self.synthetic_sessions: dict[str, SyntheticSession] = {}
        self.last_results: dict[str, ReconcileResult] = {}
        self.runtime: dict[str, DeviceRuntimeState] = {
            key: DeviceRuntimeState() for key in config.devices
        }

    async def reconcile_all(self) -> list[ReconcileResult]:
        semaphore = asyncio.Semaphore(max(1, self.config.max_concurrent_devices))

        async def reconcile_with_limit(device: DeviceConfig) -> ReconcileResult:
            async with semaphore:
                return await self.reconcile_device(device)

        results = await asyncio.gather(
            *(reconcile_with_limit(device) for device in self.config.devices.values()),
            return_exceptions=True,
        )
        output: list[ReconcileResult] = []
        for device, result in zip(self.config.devices.values(), results, strict=False):
            if isinstance(result, Exception):
                LOG.exception("reconcile failed", extra={"device": device.key})
                result = ReconcileResult(
                    device=device.key,
                    decision=Decision.DEVICE_UNAVAILABLE,
                    message=str(result),
                )
            self.last_results[device.key] = result
            output.append(result)
        return output

    async def reconcile_device(self, device: DeviceConfig) -> ReconcileResult:
        try:
            power = await self.apple_tv.power_state(device)
        except Exception as exc:
            result = self._handle_device_failure(device, exc, stage="power_state")
            self._log_decision(result)
            return result
        self._mark_success(device)

        if power.is_off:
            self._clear_failures(device)
            if device.key in self.synthetic_sessions:
                self._stop_synthetic(device, reason="Apple TV power is off")
                decision = Decision.STOP_SYNTHETIC
            elif self._stop_existing_synthetic_from_plex(device, reason="Apple TV power is off"):
                decision = Decision.STOP_SYNTHETIC
            else:
                decision = Decision.IGNORE_POWER_OFF
            result = ReconcileResult(device=device.key, decision=decision, power_state=power.state)
            self._log_decision(result)
            return result

        try:
            active_app = await self.apple_tv.active_app(device)
        except Exception as exc:
            result = self._handle_device_failure(device, exc, stage="app", power_state=power.state)
            self._log_decision(result)
            return result
        self._mark_success(device)

        if not active_app.is_infuse:
            self._clear_failures(device)
            if device.key in self.synthetic_sessions:
                self._stop_synthetic(device, reason="active app changed away from Infuse")
                decision = Decision.STOP_SYNTHETIC
            elif self._stop_existing_synthetic_from_plex(device, reason="active app changed away from Infuse"):
                decision = Decision.STOP_SYNTHETIC
            else:
                decision = Decision.IGNORE_NON_INFUSE
            result = ReconcileResult(
                device=device.key,
                decision=decision,
                power_state=power.state,
                active_app=active_app.name,
            )
            self._log_decision(result)
            return result

        try:
            playback = await self.apple_tv.playing(device)
        except Exception as exc:
            result = self._handle_device_failure(
                device,
                exc,
                stage="playing",
                power_state=power.state,
                active_app=active_app.name,
            )
            self._log_decision(result)
            return result
        self._mark_success(device)

        if not playback.is_active_media:
            self._clear_failures(device)
            if device.key in self.synthetic_sessions:
                self._stop_synthetic(device, reason="Infuse idle")
                decision = Decision.STOP_SYNTHETIC
            elif self._stop_existing_synthetic_from_plex(device, reason="Infuse idle"):
                decision = Decision.STOP_SYNTHETIC
            else:
                decision = Decision.INFUSE_IDLE
            result = ReconcileResult(
                device=device.key,
                decision=decision,
                power_state=power.state,
                active_app=active_app.name,
                playback_state=playback.state,
                title=playback.title,
                position_s=playback.position_s,
                duration_s=playback.duration_s,
            )
            self._log_decision(result)
            return result

        self._clear_failures(device)

        sessions = await asyncio.to_thread(self.plex.sessions)
        media = await asyncio.to_thread(self._resolve_media, device, playback.title or "", playback.duration_s)
        if media is None:
            result = ReconcileResult(
                device=device.key,
                decision=Decision.UNRESOLVED_MEDIA,
                power_state=power.state,
                active_app=active_app.name,
                playback_state=playback.state,
                title=playback.title,
                position_s=playback.position_s,
                duration_s=playback.duration_s,
            )
            self._log_decision(result)
            return result

        real_session = self._find_real_session(sessions, device, media)
        if real_session:
            if device.key in self.synthetic_sessions:
                self._stop_synthetic(device, reason="real Plex session appeared")
            result = ReconcileResult(
                device=device.key,
                decision=Decision.REAL_SESSION_PRESENT,
                power_state=power.state,
                active_app=active_app.name,
                playback_state=playback.state,
                title=playback.title,
                position_s=playback.position_s,
                duration_s=playback.duration_s,
                rating_key=media.rating_key,
                message=f"real sessionKey={real_session.session_key}",
            )
            self._log_decision(result)
            return result

        decision = self._upsert_synthetic(
            device,
            media,
            playback.state,
            playback.position_s,
            playback.duration_s,
            plex_sessions=sessions,
        )
        result = ReconcileResult(
            device=device.key,
            decision=decision,
            power_state=power.state,
            active_app=active_app.name,
            playback_state=playback.state,
            title=playback.title,
            position_s=playback.position_s,
            duration_s=playback.duration_s,
            rating_key=media.rating_key,
        )
        self._log_decision(result)
        return result

    def register(self, registration: Registration) -> Registration:
        return self.registrations.upsert(registration)

    def _resolve_media(self, device: DeviceConfig, title: str, duration_s: int | None) -> PlexMediaIdentity | None:
        registration = self.registrations.get_active(device.key)
        if registration:
            metadata = self.plex.get_media(registration.rating_key)
            return PlexMediaIdentity(
                rating_key=registration.rating_key,
                guid=registration.guid or metadata.guid,
                title=registration.title or metadata.title,
                duration_ms=registration.duration_ms or metadata.duration_ms,
                key=metadata.key,
                media_type=metadata.media_type,
                source=registration.source,
            )

        candidates = self.plex.resolve_by_title_duration(title, duration_s)
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            LOG.warning(
                "ambiguous media match",
                extra={"device": device.key, "title": title, "candidate_count": len(candidates)},
            )
            return None
        return None

    def _find_real_session(
        self,
        sessions: list[PlexSessionSnapshot],
        device: DeviceConfig,
        media: PlexMediaIdentity,
    ) -> PlexSessionSnapshot | None:
        for session in sessions:
            if str(session.rating_key) != str(media.rating_key):
                continue
            if session.player_machine_id == device.synthetic_client_id or session.player == device.name:
                continue
            if session.user and session.user != device.plex_user:
                continue
            return session
        return None

    def _find_synthetic_session(
        self,
        sessions: list[PlexSessionSnapshot],
        device: DeviceConfig,
        media: PlexMediaIdentity | None = None,
    ) -> PlexSessionSnapshot | None:
        for session in sessions:
            if session.player_machine_id != device.synthetic_client_id:
                continue
            if media and str(session.rating_key) != str(media.rating_key):
                continue
            return session
        return None

    def _upsert_synthetic(
        self,
        device: DeviceConfig,
        media: PlexMediaIdentity,
        state: PlaybackState,
        position_s: int | None,
        duration_s: int | None,
        plex_sessions: list[PlexSessionSnapshot] | None = None,
    ) -> Decision:
        duration_ms = media.duration_ms or ((duration_s or 0) * 1000)
        if duration_ms <= 0:
            raise RuntimeError(f"duration is required for {media.rating_key}")

        position_ms = max(0, (position_s or 0) * 1000)
        if state == PlaybackState.PAUSED and position_ms == 0:
            position_ms = 1000

        existing = self.synthetic_sessions.get(device.key)
        existing_from_plex = None
        if existing is None and plex_sessions is not None:
            existing_from_plex = self._find_synthetic_session(plex_sessions, device, media)
        if existing and existing.rating_key != media.rating_key:
            self._stop_synthetic(device, reason="media changed")
            existing = None

        self.plex.send_timeline(
            media=media,
            state=state,
            position_ms=position_ms,
            duration_ms=duration_ms,
            client_id=device.synthetic_client_id,
            device_name=f"{device.name} Infuse Bridge",
            client_ip=device.ip,
        )

        self.synthetic_sessions[device.key] = SyntheticSession(
            device=device.key,
            rating_key=media.rating_key,
            guid=media.guid,
            title=media.title,
            duration_ms=duration_ms,
            plex_user=device.plex_user,
            client_id=device.synthetic_client_id,
            device_name=f"{device.name} Infuse Bridge",
            client_ip=device.ip,
            last_position_ms=position_ms,
            last_state=state,
            updated_at=datetime.now(timezone.utc),
        )
        if existing is None and existing_from_plex is None:
            return Decision.START_SYNTHETIC
        if state == PlaybackState.PAUSED:
            return Decision.PAUSE_SYNTHETIC
        return Decision.UPDATE_SYNTHETIC

    def _mark_success(self, device: DeviceConfig) -> None:
        state = self.runtime.setdefault(device.key, DeviceRuntimeState())
        state.last_successful_poll = datetime.now(timezone.utc)

    def _clear_failures(self, device: DeviceConfig) -> None:
        state = self.runtime.setdefault(device.key, DeviceRuntimeState())
        state.consecutive_failures = 0
        state.last_successful_poll = datetime.now(timezone.utc)

    def _handle_device_failure(
        self,
        device: DeviceConfig,
        exc: Exception,
        stage: str,
        power_state: DevicePowerState = DevicePowerState.UNKNOWN,
        active_app: str | None = None,
    ) -> ReconcileResult:
        runtime = self.runtime.setdefault(device.key, DeviceRuntimeState())
        runtime.consecutive_failures += 1

        session = self.synthetic_sessions.get(device.key)
        if session and runtime.consecutive_failures < self.config.max_poll_failures:
            try:
                self._send_synthetic_keepalive(session)
                return ReconcileResult(
                    device=device.key,
                    decision=Decision.KEEPALIVE_ON_FAILURE,
                    power_state=power_state,
                    active_app=active_app,
                    playback_state=session.last_state,
                    title=session.title,
                    position_s=session.last_position_ms // 1000,
                    duration_s=session.duration_ms // 1000,
                    rating_key=session.rating_key,
                    message=(
                        f"{stage} failed; kept session alive "
                        f"({runtime.consecutive_failures}/{self.config.max_poll_failures})"
                    ),
                )
            except Exception as keepalive_exc:
                LOG.exception("failed synthetic keepalive", extra={"device": device.key, "stage": stage})
                return ReconcileResult(
                    device=device.key,
                    decision=Decision.DEVICE_UNAVAILABLE,
                    power_state=power_state,
                    active_app=active_app,
                    playback_state=session.last_state,
                    rating_key=session.rating_key,
                    message=f"{stage} failed; keepalive failed: {keepalive_exc}",
                )

        if session and runtime.consecutive_failures >= self.config.max_poll_failures:
            self._stop_synthetic(device, reason=f"{runtime.consecutive_failures} consecutive poll failures")
            return ReconcileResult(
                device=device.key,
                decision=Decision.STOP_SYNTHETIC,
                power_state=power_state,
                active_app=active_app,
                playback_state=session.last_state,
                title=session.title,
                position_s=session.last_position_ms // 1000,
                duration_s=session.duration_ms // 1000,
                rating_key=session.rating_key,
                message=f"{stage} failed {runtime.consecutive_failures} consecutive times; stopped synthetic session",
            )

        return ReconcileResult(
            device=device.key,
            decision=Decision.DEVICE_UNAVAILABLE,
            power_state=power_state,
            active_app=active_app,
            message=f"{stage} failed: {exc}",
        )

    def _send_synthetic_keepalive(self, session: SyntheticSession) -> None:
        now = datetime.now(timezone.utc)
        position_ms = session.last_position_ms
        if session.last_state == PlaybackState.PLAYING:
            elapsed_ms = int((now - session.updated_at).total_seconds() * 1000)
            position_ms = min(session.duration_ms, max(0, position_ms + elapsed_ms))

        media = PlexMediaIdentity(
            rating_key=session.rating_key,
            guid=session.guid,
            title=session.title,
            duration_ms=session.duration_ms,
            key=f"/library/metadata/{session.rating_key}",
        )
        self.plex.send_timeline(
            media=media,
            state=session.last_state,
            position_ms=position_ms,
            duration_ms=session.duration_ms,
            client_id=session.client_id,
            device_name=session.device_name,
            client_ip=session.client_ip,
        )
        session.last_position_ms = position_ms
        session.updated_at = now

    def _stop_synthetic(self, device: DeviceConfig, reason: str) -> None:
        session = self.synthetic_sessions.pop(device.key, None)
        if not session:
            return
        media = PlexMediaIdentity(
            rating_key=session.rating_key,
            guid=session.guid,
            title=session.title,
            duration_ms=session.duration_ms,
            key=f"/library/metadata/{session.rating_key}",
        )
        try:
            self.plex.send_timeline(
                media=media,
                state=PlaybackState.STOPPED,
                position_ms=session.last_position_ms,
                duration_ms=session.duration_ms,
                client_id=session.client_id,
                device_name=session.device_name,
                client_ip=device.ip,
            )
            LOG.info("stopped synthetic session", extra={"device": device.key, "reason": reason})
        except Exception:
            LOG.exception("failed to stop synthetic session", extra={"device": device.key, "reason": reason})

    def _stop_existing_synthetic_from_plex(self, device: DeviceConfig, reason: str) -> bool:
        try:
            sessions = self.plex.sessions()
        except Exception:
            LOG.exception("failed to inspect Plex sessions for stale synthetic stop", extra={"device": device.key})
            return False

        stopped = False
        for session in sessions:
            if session.player_machine_id != device.synthetic_client_id:
                continue
            if not session.rating_key:
                continue
            duration_ms = session.duration_ms or self.plex.get_media(session.rating_key).duration_ms
            if not duration_ms:
                continue
            media = PlexMediaIdentity(
                rating_key=session.rating_key,
                title=session.title,
                duration_ms=duration_ms,
                key=f"/library/metadata/{session.rating_key}",
            )
            try:
                self.plex.send_timeline(
                    media=media,
                    state=PlaybackState.STOPPED,
                    position_ms=session.view_offset_ms or 0,
                    duration_ms=duration_ms,
                    client_id=device.synthetic_client_id,
                    device_name=f"{device.name} Infuse Bridge",
                    client_ip=device.ip,
                )
                stopped = True
                LOG.info("stopped stale Plex synthetic session", extra={"device": device.key, "reason": reason})
            except Exception:
                LOG.exception("failed to stop stale Plex synthetic session", extra={"device": device.key})
        return stopped

    def _log_decision(self, result: ReconcileResult) -> None:
        LOG.info(
            "reconcile decision",
            extra={
                "device": result.device,
                "decision": result.decision,
                "power_state": result.power_state,
                "active_app": result.active_app,
                "apple_tv_state": result.playback_state,
                "title": result.title,
                "position_s": result.position_s,
                "duration_s": result.duration_s,
                "rating_key": result.rating_key,
            },
        )
