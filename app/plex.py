from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin
from xml.etree import ElementTree

import requests
from plexapi.server import PlexServer

from app.models import PlexMediaIdentity, PlaybackState


LIBRARY_IDENTIFIER = "com.plexapp.plugins.library"


@dataclass(frozen=True)
class PlexSessionSnapshot:
    rating_key: str | None
    state: str | None
    view_offset_ms: int | None
    duration_ms: int | None
    user: str | None
    player: str | None
    player_machine_id: str | None
    session_key: str | None
    title: str | None


class PlexClient:
    def __init__(self, url: str, token: str, timeout_s: float = 10.0) -> None:
        self.url = url.rstrip("/")
        self.token = token
        self.timeout_s = timeout_s
        self.session = requests.Session()

    def _url(self, path: str) -> str:
        return urljoin(f"{self.url}/", path.lstrip("/"))

    def headers(self, client_id: str, device_name: str, client_ip: str | None = None) -> dict[str, str]:
        session_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"plex-infuse-bridge:{client_id}"))
        headers = {
            "Accept": "application/xml",
            "X-Plex-Token": self.token,
            "X-Plex-Product": "Plex Infuse Bridge",
            "X-Plex-Version": "0.1.0",
            "X-Plex-Platform": "tvOS",
            "X-Plex-Platform-Version": "unknown",
            "X-Plex-Device": "Apple TV",
            "X-Plex-Device-Name": device_name,
            "X-Plex-Client-Identifier": client_id,
            "X-Plex-Provides": "player",
            "X-Plex-Features": "external-media",
            "X-Plex-Language": "en",
            "X-Plex-Session-Identifier": session_id,
            "X-Plex-Session-Id": session_id,
            "X-Plex-Playback-Session-Id": session_id,
        }
        if client_ip:
            headers["X-Forwarded-For"] = client_ip
            headers["X-Real-IP"] = client_ip
            headers["Forwarded"] = f"for={client_ip}"
        return headers

    def get_media(self, rating_key: str) -> PlexMediaIdentity:
        response = self.session.get(
            self._url(f"/library/metadata/{rating_key}"),
            headers={"X-Plex-Token": self.token, "Accept": "application/xml"},
            timeout=self.timeout_s,
        )
        response.raise_for_status()
        root = ElementTree.fromstring(response.content)
        item = next((child for child in root if child.tag in {"Video", "Track", "Photo"}), None)
        if item is None:
            raise RuntimeError(f"No Plex metadata found for ratingKey={rating_key}")
        duration = item.attrib.get("duration")
        return PlexMediaIdentity(
            rating_key=str(rating_key),
            guid=item.attrib.get("guid"),
            title=item.attrib.get("title"),
            duration_ms=int(duration) if duration and duration.isdigit() else None,
            key=item.attrib.get("key") or f"/library/metadata/{rating_key}",
            media_type=item.attrib.get("type") or "video",
            source="plex_metadata",
        )

    def sessions(self) -> list[PlexSessionSnapshot]:
        response = self.session.get(
            self._url("/status/sessions"),
            headers={"X-Plex-Token": self.token, "Accept": "application/xml"},
            timeout=self.timeout_s,
        )
        response.raise_for_status()
        root = ElementTree.fromstring(response.content)
        output: list[PlexSessionSnapshot] = []
        for item in root:
            if item.tag not in {"Video", "Track", "Photo"}:
                continue
            player = item.find("Player")
            user = item.find("User")
            output.append(
                PlexSessionSnapshot(
                    rating_key=item.attrib.get("ratingKey"),
                    state=player.attrib.get("state") if player is not None else item.attrib.get("state"),
                    view_offset_ms=_int_or_none(item.attrib.get("viewOffset")),
                    duration_ms=_int_or_none(item.attrib.get("duration")),
                    user=user.attrib.get("title") if user is not None else None,
                    player=player.attrib.get("title") if player is not None else None,
                    player_machine_id=player.attrib.get("machineIdentifier") if player is not None else None,
                    session_key=item.attrib.get("sessionKey"),
                    title=item.attrib.get("title"),
                )
            )
        return output

    def plexapi_sessions(self) -> list[Any]:
        return PlexServer(self.url, self.token).sessions()

    def send_timeline(
        self,
        media: PlexMediaIdentity,
        state: PlaybackState,
        position_ms: int,
        duration_ms: int,
        client_id: str,
        device_name: str,
        client_ip: str | None = None,
    ) -> None:
        params = {
            "ratingKey": media.rating_key,
            "key": media.key or f"/library/metadata/{media.rating_key}",
            "identifier": LIBRARY_IDENTIFIER,
            "time": max(0, position_ms),
            "state": "stopped" if state == PlaybackState.IDLE else state.value,
            "duration": duration_ms,
        }
        response = self.session.get(
            self._url("/:/timeline"),
            headers=self.headers(client_id=client_id, device_name=device_name, client_ip=client_ip),
            params=params,
            timeout=self.timeout_s,
        )
        response.raise_for_status()

    def resolve_by_title_duration(self, title: str, duration_s: int | None) -> list[PlexMediaIdentity]:
        plex = PlexServer(self.url, self.token)
        candidates = []
        episode_match = _parse_infuse_episode_title(title)
        if episode_match:
            show_title, season, episode = episode_match
            for section in plex.library.sections():
                if section.type != "show":
                    continue
                for show in section.search(title=show_title):
                    if getattr(show, "title", "").casefold() != show_title.casefold():
                        continue
                    try:
                        candidates.append(show.episode(season=season, episode=episode))
                    except Exception:
                        continue
        else:
            for section in plex.library.sections():
                for result in section.search(title=title):
                    if getattr(result, "title", "").casefold() == title.casefold():
                        candidates.append(result)

        identities = []
        for item in candidates:
            item_duration_ms = getattr(item, "duration", None)
            if duration_s is not None and item_duration_ms is not None:
                if abs((item_duration_ms / 1000) - duration_s) > 90:
                    continue
            identities.append(
                PlexMediaIdentity(
                    rating_key=str(item.ratingKey),
                    guid=getattr(item, "guid", None),
                    title=getattr(item, "title", None),
                    duration_ms=item_duration_ms,
                    key=getattr(item, "key", None),
                    media_type=getattr(item, "type", None) or "video",
                    source="title_duration",
                )
            )
        return identities


def _int_or_none(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _parse_infuse_episode_title(title: str) -> tuple[str, int, int] | None:
    import re

    match = re.match(r"^(.*?) - S(\d+) ∙ E(\d+) - .*$", title)
    if not match:
        return None
    return match.group(1), int(match.group(2)), int(match.group(3))
