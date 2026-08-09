#!/usr/bin/env python3
"""Manual Plex timeline proof of concept for the Infuse bridge."""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin
from xml.etree import ElementTree

import requests
from plexapi.server import PlexServer


VALID_STATES = {"playing", "paused", "stopped", "buffering"}
LIBRARY_IDENTIFIER = "com.plexapp.plugins.library"


@dataclass(frozen=True)
class MediaInfo:
    rating_key: str
    key: str
    title: str | None
    duration_ms: int | None
    media_type: str


@dataclass(frozen=True)
class PlayQueueInfo:
    play_queue_id: str | None
    play_queue_item_id: str | None


def seconds_to_ms(value: float | None) -> int | None:
    if value is None:
        return None
    return int(round(value * 1000))


def redact_token(text: str, token: str) -> str:
    return text.replace(token, "<redacted>") if token else text


class PlexTimelinePoc:
    def __init__(
        self,
        plex_url: str,
        token: str,
        client_id: str,
        device_name: str,
        product: str,
        version: str,
        timeout: float,
        session_id: str | None = None,
    ) -> None:
        self.plex_url = plex_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.session = requests.Session()
        playback_session_id = session_id or self._stable_session_id(client_id)
        self.headers = {
            "Accept": "application/xml",
            "X-Plex-Token": token,
            "X-Plex-Product": product,
            "X-Plex-Version": version,
            "X-Plex-Platform": "tvOS",
            "X-Plex-Platform-Version": "unknown",
            "X-Plex-Device": "Apple TV",
            "X-Plex-Device-Name": device_name,
            "X-Plex-Client-Identifier": client_id,
            "X-Plex-Provides": "player",
            "X-Plex-Features": "external-media",
            "X-Plex-Language": "en",
            "X-Plex-Session-Identifier": playback_session_id,
            "X-Plex-Session-Id": playback_session_id,
            "X-Plex-Playback-Session-Id": playback_session_id,
        }

    @staticmethod
    def _stable_session_id(client_id: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"plex-infuse-bridge:{client_id}"))

    def _url(self, path: str) -> str:
        return urljoin(f"{self.plex_url}/", path.lstrip("/"))

    def get_identity(self) -> str:
        response = self.session.get(
            self._url("/identity"),
            headers=self.headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        root = ElementTree.fromstring(response.content)
        machine_id = root.attrib.get("machineIdentifier")
        if not machine_id:
            raise RuntimeError("Plex /identity response did not include machineIdentifier")
        return machine_id

    def get_media_info(self, rating_key: str) -> MediaInfo:
        response = self.session.get(
            self._url(f"/library/metadata/{rating_key}"),
            headers=self.headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        root = ElementTree.fromstring(response.content)
        media = next(
            (
                child
                for child in root
                if child.tag in {"Video", "Track", "Photo"}
                and child.attrib.get("ratingKey") == str(rating_key)
            ),
            None,
        )
        if media is None:
            raise RuntimeError(f"Could not find metadata for ratingKey={rating_key}")
        duration = media.attrib.get("duration")
        return MediaInfo(
            rating_key=str(rating_key),
            key=media.attrib.get("key") or f"/library/metadata/{rating_key}",
            title=media.attrib.get("title"),
            duration_ms=int(duration) if duration and duration.isdigit() else None,
            media_type=media.attrib.get("type") or "video",
        )

    def create_playqueue(self, media: MediaInfo) -> PlayQueueInfo:
        machine_id = self.get_identity()
        params = {
            "type": media.media_type,
            "uri": f"server://{machine_id}/{LIBRARY_IDENTIFIER}{media.key}",
        }
        response = self.session.post(
            self._url("/playQueues"),
            headers=self.headers,
            params=params,
            timeout=self.timeout,
        )
        response.raise_for_status()
        root = ElementTree.fromstring(response.content)
        return PlayQueueInfo(
            play_queue_id=root.attrib.get("playQueueID"),
            play_queue_item_id=root.attrib.get("playQueueSelectedItemID"),
        )

    def send_timeline(
        self,
        media: MediaInfo,
        state: str,
        position_ms: int,
        duration_ms: int,
        play_queue_item_id: str | None = None,
    ) -> requests.Response:
        params: dict[str, Any] = {
            "ratingKey": media.rating_key,
            "key": media.key,
            "identifier": LIBRARY_IDENTIFIER,
            "time": position_ms,
            "state": state,
            "duration": duration_ms,
        }
        if play_queue_item_id:
            params["playQueueItemID"] = play_queue_item_id
        response = self.session.get(
            self._url("/:/timeline"),
            headers=self.headers,
            params=params,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response

    def get_status_sessions(self) -> list[dict[str, Any]]:
        response = self.session.get(
            self._url("/status/sessions"),
            headers=self.headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        root = ElementTree.fromstring(response.content)
        sessions: list[dict[str, Any]] = []
        for item in root:
            if item.tag not in {"Video", "Track", "Photo"}:
                continue
            player = item.find("Player")
            user = item.find("User")
            sessions.append(
                {
                    "tag": item.tag,
                    "type": item.attrib.get("type"),
                    "ratingKey": item.attrib.get("ratingKey"),
                    "title": item.attrib.get("title"),
                    "sessionKey": item.attrib.get("sessionKey"),
                    "viewOffset": item.attrib.get("viewOffset"),
                    "duration": item.attrib.get("duration"),
                    "user": user.attrib.get("title") if user is not None else None,
                    "player": player.attrib.get("title") if player is not None else None,
                    "player_address": player.attrib.get("address") if player is not None else None,
                    "player_machine_id": player.attrib.get("machineIdentifier") if player is not None else None,
                    "state": player.attrib.get("state") if player is not None else item.attrib.get("state"),
                }
            )
        return sessions

    def get_plexapi_sessions(self) -> list[dict[str, Any]]:
        plex = PlexServer(self.plex_url, self.token)
        output = []
        for item in plex.sessions():
            player = getattr(item, "player", None)
            session = getattr(item, "session", None)
            output.append(
                {
                    "ratingKey": str(getattr(item, "ratingKey", "")),
                    "title": getattr(item, "title", None),
                    "sessionKey": getattr(item, "sessionKey", None),
                    "viewOffset": getattr(item, "viewOffset", None),
                    "user": getattr(getattr(item, "user", None), "title", None),
                    "player": getattr(player, "title", None),
                    "player_machine_id": getattr(player, "machineIdentifier", None),
                    "state": getattr(player, "state", None),
                    "session_id": getattr(session, "id", None),
                }
            )
        return output


def print_sessions(label: str, sessions: list[dict[str, Any]], rating_key: str) -> None:
    print(f"\n{label}: {len(sessions)} session(s)")
    for item in sessions:
        marker = "*" if str(item.get("ratingKey")) == str(rating_key) else " "
        print(
            f"{marker} ratingKey={item.get('ratingKey')} "
            f"state={item.get('state')} "
            f"viewOffset={item.get('viewOffset')} "
            f"user={item.get('user')} "
            f"player={item.get('player')} "
            f"sessionKey={item.get('sessionKey')} "
            f"title={item.get('title')}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send Plex /:/timeline requests for one synthetic playback session.",
    )
    parser.add_argument("--plex-url", default=os.getenv("PLEX_URL", "http://127.0.0.1:32400"))
    parser.add_argument("--token", default=os.getenv("PLEX_TOKEN"))
    parser.add_argument("--rating-key", required=True)
    parser.add_argument("--state", required=True, choices=sorted(VALID_STATES))
    parser.add_argument("--position", type=float, required=True, help="Playback position in seconds.")
    parser.add_argument("--duration", type=float, help="Media duration in seconds. Defaults to Plex metadata duration.")
    parser.add_argument("--device-name", default="Infuse Bridge Apple TV")
    parser.add_argument("--client-id", default="infuse-bridge-poc")
    parser.add_argument("--user", help="Expected Plex username; informational only.")
    parser.add_argument("--product", default="Plex Infuse Bridge")
    parser.add_argument("--version", default="0.1.0")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--session-id", help="Override playback/session ID headers.")
    parser.add_argument("--create-playqueue", action="store_true")
    parser.add_argument("--play-queue-item-id")
    parser.add_argument("--heartbeat-count", type=int, default=1)
    parser.add_argument("--interval", type=float, default=10.0, help="Seconds between heartbeat requests.")
    parser.add_argument("--send-stop-on-exit", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.token:
        print("PLEX_TOKEN is required via environment or --token.", file=sys.stderr)
        return 2
    if args.heartbeat_count < 1:
        print("--heartbeat-count must be at least 1.", file=sys.stderr)
        return 2

    poc = PlexTimelinePoc(
        plex_url=args.plex_url,
        token=args.token,
        client_id=args.client_id,
        device_name=args.device_name,
        product=args.product,
        version=args.version,
        timeout=args.timeout,
        session_id=args.session_id,
    )

    media = poc.get_media_info(args.rating_key)
    duration_ms = seconds_to_ms(args.duration) or media.duration_ms
    if duration_ms is None:
        print("Duration is required because Plex metadata did not include duration.", file=sys.stderr)
        return 2

    play_queue_item_id = args.play_queue_item_id
    if args.create_playqueue:
        playqueue = poc.create_playqueue(media)
        play_queue_item_id = playqueue.play_queue_item_id or play_queue_item_id
        print(
            "Created playQueue "
            f"playQueueID={playqueue.play_queue_id} "
            f"playQueueItemID={playqueue.play_queue_item_id}"
        )

    if args.user:
        print(f"Expected Plex user: {args.user} (actual user is determined by PLEX_TOKEN)")

    position_ms = seconds_to_ms(args.position)
    assert position_ms is not None
    last_position_ms = position_ms

    try:
        for index in range(args.heartbeat_count):
            response = poc.send_timeline(
                media=media,
                state=args.state,
                position_ms=last_position_ms,
                duration_ms=duration_ms,
                play_queue_item_id=play_queue_item_id,
            )
            print(
                f"Timeline {index + 1}/{args.heartbeat_count}: "
                f"HTTP {response.status_code} "
                f"state={args.state} "
                f"time={last_position_ms}ms "
                f"duration={duration_ms}ms "
                f"url={redact_token(response.url, args.token)}"
            )
            if index + 1 < args.heartbeat_count:
                time.sleep(args.interval)
                if args.state == "playing":
                    last_position_ms = min(
                        duration_ms,
                        last_position_ms + seconds_to_ms(args.interval),
                    )
    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        if args.send_stop_on_exit and args.state != "stopped":
            response = poc.send_timeline(
                media=media,
                state="stopped",
                position_ms=last_position_ms,
                duration_ms=duration_ms,
                play_queue_item_id=play_queue_item_id,
            )
            print(f"Stop on exit: HTTP {response.status_code}")

    status_sessions = poc.get_status_sessions()
    print_sessions("/status/sessions", status_sessions, args.rating_key)

    plexapi_sessions = poc.get_plexapi_sessions()
    print_sessions("plex.sessions()", plexapi_sessions, args.rating_key)

    matched = any(str(item.get("ratingKey")) == str(args.rating_key) for item in status_sessions)
    if matched:
        print("\nMATCH: Plex reports a current session for this ratingKey.")
        return 0

    print("\nNO MATCH: Plex did not report a current session for this ratingKey.")
    return 1 if args.state != "stopped" else 0


if __name__ == "__main__":
    raise SystemExit(main())
