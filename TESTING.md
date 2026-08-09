# Testing

## Automated Tests

Run:

```bash
.venv/bin/python -m pytest -q
```

Current coverage includes:

- active-app parser
- playback parser
- power-state parser
- pyatv traceback sanitization
- power-off gate short-circuiting
- transient failure keepalive behavior
- stop-after-max-failures behavior

## Manual Test Plan

1. Start Infuse playback on one Apple TV.
2. Confirm `atvremote --id <id> power_state` returns `PowerState.On`.
3. Confirm `atvremote --id <id> app` returns Infuse.
4. Confirm `atvremote --id <id> playing` returns title, state, and position.
5. Run one reconcile pass or start the service.
6. Confirm Plex Dashboard shows a session.
7. Confirm `/status/sessions` includes the rating key and synthetic device.
8. Confirm `plex.sessions()` sees the session.
9. Pause/resume playback and verify state/position update.
10. Power off the Apple TV and verify the synthetic session stops.

## Manual Scenarios Still Worth Testing

- native Plex playback already active
- Infuse playback launched with exact `/playback/register` metadata
- manual Infuse playback resolved by title + duration
- ambiguous title matches remain observe-only
- Tautulli current activity and history behavior
- bridge restart during active playback
- simultaneous playback on multiple Apple TVs

