import asyncio

from app.config import BridgeConfig, DeviceConfig, PlexConfig, ServerConfig
from app.models import AppleTvPower, Decision, DevicePowerState, PlaybackState, SyntheticSession
from app.reconciler import Reconciler


class FakeAppleTv:
    def __init__(self) -> None:
        self.active_app_called = False
        self.playing_called = False

    async def power_state(self, device):
        return AppleTvPower(state=DevicePowerState.OFF, raw="PowerState.Off\n")

    async def active_app(self, device):
        self.active_app_called = True
        raise AssertionError("active_app should not be called when power is off")

    async def playing(self, device):
        self.playing_called = True
        raise AssertionError("playing should not be called when power is off")


class FakePlex:
    def __init__(self) -> None:
        self.timeline_calls = []

    def sessions(self):
        return []

    def send_timeline(self, **kwargs):
        self.timeline_calls.append(kwargs)


def test_power_off_short_circuits_before_app_or_playback() -> None:
    device = DeviceConfig(
        key="media_room",
        name="Media Room",
        ip="192.0.2.21",
        mac_address="A1B2C3D4E5F6",
        plex_user="plex-user",
        synthetic_client_id="infuse-bridge-media-room",
    )
    config = BridgeConfig(
        plex=PlexConfig(url="http://plex.example:32400", token="token"),
        devices={"den": device},
        server=ServerConfig(),
    )
    apple_tv = FakeAppleTv()
    reconciler = Reconciler(config=config, apple_tv=apple_tv, plex=FakePlex())

    result = asyncio.run(reconciler.reconcile_device(device))

    assert result.decision == Decision.IGNORE_POWER_OFF
    assert not apple_tv.active_app_called
    assert not apple_tv.playing_called


class FailingAppleTv:
    async def power_state(self, device):
        raise RuntimeError("temporary timeout")


def test_failure_keepalive_before_max_failures() -> None:
    device = _device()
    config = _config(device)
    plex = FakePlex()
    reconciler = Reconciler(config=config, apple_tv=FailingAppleTv(), plex=plex)
    reconciler.synthetic_sessions[device.key] = SyntheticSession(
        device=device.key,
        rating_key="12345",
        guid=None,
        title="Example Episode",
        duration_ms=3_690_000,
        plex_user="plex-user",
        client_id=device.synthetic_client_id,
        device_name="Media Room Infuse Bridge",
        client_ip=device.ip,
        last_position_ms=1_000_000,
        last_state=PlaybackState.PLAYING,
    )

    result = asyncio.run(reconciler.reconcile_device(device))

    assert result.decision == Decision.KEEPALIVE_ON_FAILURE
    assert result.rating_key == "12345"
    assert len(plex.timeline_calls) == 1
    assert plex.timeline_calls[0]["state"] == PlaybackState.PLAYING
    assert plex.timeline_calls[0]["client_ip"] == device.ip


def test_failure_stops_at_max_failures() -> None:
    device = _device()
    config = _config(device)
    plex = FakePlex()
    reconciler = Reconciler(config=config, apple_tv=FailingAppleTv(), plex=plex)
    reconciler.runtime[device.key].consecutive_failures = config.max_poll_failures - 1
    reconciler.synthetic_sessions[device.key] = SyntheticSession(
        device=device.key,
        rating_key="12345",
        guid=None,
        title="Example Episode",
        duration_ms=3_690_000,
        plex_user="plex-user",
        client_id=device.synthetic_client_id,
        device_name="Media Room Infuse Bridge",
        client_ip=device.ip,
        last_position_ms=1_000_000,
        last_state=PlaybackState.PLAYING,
    )

    result = asyncio.run(reconciler.reconcile_device(device))

    assert result.decision == Decision.STOP_SYNTHETIC
    assert device.key not in reconciler.synthetic_sessions
    assert len(plex.timeline_calls) == 1
    assert plex.timeline_calls[0]["state"] == PlaybackState.STOPPED


def _device() -> DeviceConfig:
    return DeviceConfig(
        key="media_room",
        name="Media Room",
        ip="192.0.2.21",
        mac_address="A1B2C3D4E5F6",
        plex_user="plex-user",
        synthetic_client_id="infuse-bridge-media-room",
    )


def _config(device: DeviceConfig) -> BridgeConfig:
    return BridgeConfig(
        plex=PlexConfig(url="http://plex.example:32400", token="token"),
        devices={device.key: device},
        server=ServerConfig(),
        max_poll_failures=5,
    )
