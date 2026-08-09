from __future__ import annotations

import asyncio
import re

from app.config import DeviceConfig
from app.models import ActiveApp, AppleTvPlayback, AppleTvPower, DevicePowerState, PlaybackState


APP_RE = re.compile(r"^App:\s*(?P<name>.*?)\s*(?:\((?P<bundle>[^)]+)\))?\s*$", re.MULTILINE)
POSITION_PAIR_RE = re.compile(r"Position:\s*(?P<position>\d+)\s*/\s*(?P<duration>\d+)s")
POSITION_SINGLE_RE = re.compile(r"Position:\s*(?P<position>\d+)s?")
TOTAL_TIME_RE = re.compile(r"Total time:\s*(?P<duration>\d+)")
POWER_RE = re.compile(r"PowerState\.(?P<state>\w+)")


def parse_active_app(output: str) -> ActiveApp:
    match = APP_RE.search(output)
    if not match:
        return ActiveApp(name=None, bundle_id=None, raw=output)
    return ActiveApp(
        name=(match.group("name") or "").strip() or None,
        bundle_id=(match.group("bundle") or "").strip() or None,
        raw=output,
    )


def parse_playing(output: str) -> AppleTvPlayback:
    state = PlaybackState.UNKNOWN
    title = None
    media_type = None
    position_s = None
    duration_s = None

    for raw_line in output.splitlines():
        line = raw_line.strip()
        if line.startswith("Device state:"):
            value = line.split(":", 1)[1].strip().casefold()
            state = {
                "playing": PlaybackState.PLAYING,
                "paused": PlaybackState.PAUSED,
                "stopped": PlaybackState.STOPPED,
                "idle": PlaybackState.IDLE,
            }.get(value, PlaybackState.UNKNOWN)
        elif line.startswith("Title:"):
            title = line.split(":", 1)[1].strip() or None
        elif line.startswith("Media type:"):
            media_type = line.split(":", 1)[1].strip() or None

    pair = POSITION_PAIR_RE.search(output)
    if pair:
        position_s = int(pair.group("position"))
        duration_s = int(pair.group("duration"))
    else:
        single = POSITION_SINGLE_RE.search(output)
        if single:
            position_s = int(single.group("position"))

    total = TOTAL_TIME_RE.search(output)
    if total:
        duration_s = int(total.group("duration"))

    return AppleTvPlayback(
        state=state,
        title=title,
        position_s=position_s,
        duration_s=duration_s,
        media_type=media_type,
        raw=output,
    )


def parse_power_state(output: str) -> AppleTvPower:
    match = POWER_RE.search(output)
    value = (match.group("state") if match else output.strip()).casefold()
    state = {
        "on": DevicePowerState.ON,
        "off": DevicePowerState.OFF,
    }.get(value, DevicePowerState.UNKNOWN)
    return AppleTvPower(state=state, raw=output)


class AppleTvClient:
    def __init__(self, atvremote_path: str = "atvremote", timeout_s: float = 8.0) -> None:
        self.atvremote_path = atvremote_path
        self.timeout_s = timeout_s

    async def _run(self, device: DeviceConfig, command: str) -> str:
        process = await asyncio.create_subprocess_exec(
            self.atvremote_path,
            "--id",
            device.mac_address,
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.timeout_s)
        except asyncio.TimeoutError as exc:
            process.kill()
            await process.wait()
            raise RuntimeError(f"atvremote {command} timed out for {device.key}") from exc
        if process.returncode != 0:
            message = stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"atvremote {command} failed for {device.key}: {_sanitize_error(message)}")
        return stdout.decode("utf-8", errors="replace")

    async def active_app(self, device: DeviceConfig) -> ActiveApp:
        return parse_active_app(await self._run(device, "app"))

    async def playing(self, device: DeviceConfig) -> AppleTvPlayback:
        return parse_playing(await self._run(device, "playing"))

    async def power_state(self, device: DeviceConfig) -> AppleTvPower:
        return parse_power_state(await self._run(device, "power_state"))


def _sanitize_error(message: str) -> str:
    lines = [line.strip() for line in message.splitlines() if line.strip()]
    if not lines:
        return "unknown error"
    for line in reversed(lines):
        if "Error:" in line or "Exception:" in line or "ProtocolError:" in line:
            return line
    return lines[-1]
