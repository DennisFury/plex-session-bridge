# Research Notes

## Plex Timeline Behavior

PlexAPI implements media timeline updates with `/:/timeline` using parameters
like:

```text
ratingKey=<ratingKey>
key=/library/metadata/<ratingKey>
identifier=com.plexapp.plugins.library
time=<milliseconds>
state=<playing|paused|stopped>
duration=<milliseconds>
```

The bridge sends these requests directly with `requests` instead of relying on
`plexapi.updateTimeline()` because it must control the synthetic client headers
per Apple TV.

Important headers:

- `X-Plex-Token`
- `X-Plex-Product`
- `X-Plex-Version`
- `X-Plex-Platform`
- `X-Plex-Device`
- `X-Plex-Device-Name`
- `X-Plex-Client-Identifier`
- `X-Plex-Playback-Session-Id`

Each physical Apple TV should have one stable synthetic
`X-Plex-Client-Identifier`, such as `infuse-bridge-media-room`.

## POC Findings

Timeline-only reporting was sufficient to create active Plex sessions in local
testing. The sessions appeared through:

- Plex Dashboard
- `/status/sessions`
- `plex.sessions()`

An initial `paused` timeline at exactly `0 ms` may not create a visible Plex
session. The bridge clamps paused-at-start reporting to `1000 ms` when needed.

## Tautulli

Tautulli reads Plex current activity from `/status/sessions` and keys activity
off Plex-provided fields such as `sessionKey`, `ratingKey`, `viewOffset`, user,
player, and state. The bridge intentionally reports to Plex only and does not
write to Tautulli.

## Apple TV Observations

The current implementation uses `atvremote` subprocess calls because the CLI is
reliable and exposes the required fields.

Useful commands:

```bash
atvremote --id A1B2C3D4E5F6 power_state
atvremote --id A1B2C3D4E5F6 app
atvremote --id A1B2C3D4E5F6 playing
```

Observed playback position forms include:

```text
Position: 120/1800s (6.7%)
```

and:

```text
Position: 120s
```

The parser supports both.

## Safety Gates

The bridge gates reconciliation in this order:

1. Apple TV power state
2. active tvOS app
3. Infuse playback state
4. existing Plex sessions
5. media identity resolution
6. synthetic timeline update

Confirmed `PowerState.Off`, non-Infuse app, and Infuse idle/stopped states stop
or suppress synthetic reporting. Unknown command failures use a grace path.

## Retry And Keepalive Behavior

`atvremote` can intermittently time out. A failed command is not treated as a
confirmed stop.

If a synthetic session already exists, the bridge repeats the last known
timeline state until `max_poll_failures` is reached. For `playing`, position is
advanced by elapsed wall-clock time; for `paused`, position is held.

Default:

```text
max_poll_failures: 5
```

The reconciler also limits simultaneous device polls:

```text
max_concurrent_devices: 2
```

## Dashboard IP And Bandwidth

Synthetic timeline requests originate from the bridge host, so Plex may display
the bridge host IP as the player address. The bridge sends `X-Forwarded-For`,
`X-Real-IP`, and `Forwarded` as best-effort client-IP hints, but Plex may ignore
them.

Per-stream bandwidth values in Plex Dashboard may be imperfect for synthetic
sessions because no actual media bytes flow through the bridge.

