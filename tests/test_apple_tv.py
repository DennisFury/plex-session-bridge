from app.apple_tv import _sanitize_error, parse_active_app, parse_playing, parse_power_state
from app.models import DevicePowerState, PlaybackState


def test_parse_infuse_app() -> None:
    active_app = parse_active_app("App: Infuse (com.firecore.infuse)\n")

    assert active_app.name == "Infuse"
    assert active_app.bundle_id == "com.firecore.infuse"
    assert active_app.is_infuse


def test_parse_position_pair() -> None:
    playback = parse_playing(
        """
  Media type: Video
Device state: Playing
       Title: Example Show - S1 ∙ E1 - Pilot
    Position: 759/3690s (20.6%)
      Repeat: Off
     Shuffle: Off
"""
    )

    assert playback.state == PlaybackState.PLAYING
    assert playback.title == "Example Show - S1 ∙ E1 - Pilot"
    assert playback.position_s == 759
    assert playback.duration_s == 3690


def test_parse_position_single() -> None:
    playback = parse_playing(
        """
  Media type: Unknown
Device state: Playing
       Title: Another Example - S2 ∙ E6 - The Return
    Position: 812s
      Repeat: Off
     Shuffle: Off
"""
    )

    assert playback.state == PlaybackState.PLAYING
    assert playback.position_s == 812
    assert playback.duration_s is None


def test_parse_power_state_off() -> None:
    power = parse_power_state("PowerState.Off\n")

    assert power.state == DevicePowerState.OFF
    assert power.is_off


def test_sanitize_pyatv_traceback() -> None:
    message = """
Traceback (most recent call last):
  File "<python-site-packages>/pyatv/scripts/atvremote.py", line 998, in _run_application
    return await cli_handler(loop)
pyatv.exceptions.ProtocolError: Command _touchStart failed

>>> An error occurred, full stack trace above
"""

    assert _sanitize_error(message) == "pyatv.exceptions.ProtocolError: Command _touchStart failed"
