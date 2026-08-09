from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum


class PlaybackState(StrEnum):
    PLAYING = "playing"
    PAUSED = "paused"
    STOPPED = "stopped"
    IDLE = "idle"
    UNKNOWN = "unknown"


class DevicePowerState(StrEnum):
    ON = "on"
    OFF = "off"
    UNKNOWN = "unknown"


class Decision(StrEnum):
    IGNORE_POWER_OFF = "IGNORE_POWER_OFF"
    IGNORE_NON_INFUSE = "IGNORE_NON_INFUSE"
    INFUSE_IDLE = "INFUSE_IDLE"
    REAL_SESSION_PRESENT = "REAL_SESSION_PRESENT"
    START_SYNTHETIC = "START_SYNTHETIC"
    UPDATE_SYNTHETIC = "UPDATE_SYNTHETIC"
    PAUSE_SYNTHETIC = "PAUSE_SYNTHETIC"
    STOP_SYNTHETIC = "STOP_SYNTHETIC"
    KEEPALIVE_ON_FAILURE = "KEEPALIVE_ON_FAILURE"
    AMBIGUOUS_MEDIA = "AMBIGUOUS_MEDIA"
    UNRESOLVED_MEDIA = "UNRESOLVED_MEDIA"
    DEVICE_UNAVAILABLE = "DEVICE_UNAVAILABLE"


@dataclass(frozen=True)
class AppleTvPlayback:
    state: PlaybackState
    title: str | None = None
    position_s: int | None = None
    duration_s: int | None = None
    media_type: str | None = None
    raw: str = ""

    @property
    def is_active_media(self) -> bool:
        return self.state in {PlaybackState.PLAYING, PlaybackState.PAUSED} and bool(self.title)


@dataclass(frozen=True)
class ActiveApp:
    name: str | None
    bundle_id: str | None
    raw: str = ""

    @property
    def is_infuse(self) -> bool:
        return self.bundle_id == "com.firecore.infuse" or (self.name or "").casefold() == "infuse"


@dataclass(frozen=True)
class AppleTvPower:
    state: DevicePowerState
    raw: str = ""

    @property
    def is_off(self) -> bool:
        return self.state == DevicePowerState.OFF


@dataclass(frozen=True)
class PlexMediaIdentity:
    rating_key: str
    guid: str | None = None
    title: str | None = None
    duration_ms: int | None = None
    key: str | None = None
    media_type: str = "video"
    source: str = "unknown"


@dataclass
class Registration:
    device: str
    rating_key: str
    guid: str | None = None
    title: str | None = None
    duration_ms: int | None = None
    media_part_key: str | None = None
    filename: str | None = None
    plex_user: str | None = None
    source: str = "infuse_deeplink"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc) + timedelta(minutes=10))
    active: bool = False


@dataclass
class SyntheticSession:
    device: str
    rating_key: str
    guid: str | None
    title: str | None
    duration_ms: int
    plex_user: str
    client_id: str
    device_name: str
    client_ip: str | None
    last_position_ms: int
    last_state: PlaybackState
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class DeviceRuntimeState:
    consecutive_failures: int = 0
    last_successful_poll: datetime | None = None


@dataclass(frozen=True)
class ReconcileResult:
    device: str
    decision: Decision
    power_state: DevicePowerState = DevicePowerState.UNKNOWN
    active_app: str | None = None
    playback_state: PlaybackState = PlaybackState.UNKNOWN
    title: str | None = None
    position_s: int | None = None
    duration_s: int | None = None
    rating_key: str | None = None
    message: str | None = None
