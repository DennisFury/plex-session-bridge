# Plex Infuse Bridge

Plex Infuse Bridge is a small Python service that makes Infuse playback on Apple
TV appear to Plex Media Server as active Plex playback sessions.

It is useful when you launch Infuse with deep links to direct Plex media URLs.
Infuse can play the media, but Plex will not show an active session, update
resume position, or expose playback to tools that depend on Plex sessions. This
bridge fills that gap by observing Apple TV playback and sending Plex timeline
updates with a stable synthetic Plex client identity.

Current scope:

- Apple TV only
- Infuse only
- Plex Media Server via HTTP timeline/session APIs
- `atvremote`/pyatv shell commands for Apple TV state

The design could support other players or platforms later, but the safety gates
and parsers in this repo are built for Apple TV + Infuse today.

## Safety Model

The bridge is intentionally conservative. It does not blindly send every Apple
TV media title to Plex.

For each configured Apple TV, the reconciliation order is:

1. Check Apple TV power state.
2. If power is off, stop any synthetic session and do nothing else.
3. Check the active tvOS app.
4. If the active app is not Infuse, stop any synthetic Infuse session and ignore
   playback.
5. If Infuse is active, query playback state/title/position.
6. Check Plex for an existing real session.
7. Only synthesize Plex playback if no real matching Plex session exists.

This prevents YouTube, Music, Netflix, Prime Video, the native Plex app, and
other Apple TV apps from being reported to Plex.

## What It Does

- Creates Plex Dashboard sessions for Infuse playback.
- Updates Plex current sessions via `/status/sessions`.
- Updates `plex.sessions()` consumers.
- Keeps Tautulli-compatible behavior by reporting to Plex, not Tautulli.
- Tracks multiple Apple TVs independently.
- Uses one stable synthetic client ID per physical Apple TV.
- Keeps existing sessions alive through brief `atvremote` failures.
- Stops synthetic sessions when Infuse stops, the app changes, or the Apple TV
  powers off.

## What It Does Not Do

- It does not modify the Plex database.
- It does not modify the Tautulli database.
- It does not replace the Infuse deep-link launcher.
- It does not support non-Apple-TV clients yet.
- It does not support non-Infuse apps yet.
- It cannot guarantee Plex Dashboard will display the real Apple TV IP. Plex may
  show the bridge host IP because the bridge is the TCP client sending timeline
  updates.

## Install

### 1. Prerequisites

- Python 3.11+
- Plex Media Server reachable from the bridge host
- A Plex token for the user whose playback/history should be updated
- Apple TV devices with Infuse installed
- Working pyatv/`atvremote` access to every Apple TV

This bridge uses [`pyatv`](https://github.com/postlund/pyatv), specifically the
`atvremote` command that ships with pyatv. Pair every Apple TV before starting
the bridge. The pyatv docs cover pairing here:
[Pairing with a device](https://pyatv.dev/documentation/atvremote/#pairing-with-a-device).

For the commands this bridge uses:

- `playing` depends on media playback metadata, commonly provided by `mrp`.
- `app` and `power_state` depend on tvOS companion/device state support,
  commonly provided by `companion`.
- In practice, pair all supported, non-disabled protocols shown by
  `atvremote scan`. At minimum, make sure `mrp` and `companion` are paired when
  available.

Example pairing flow for one Apple TV:

```bash
atvremote scan
atvremote --id A1B2C3D4E5F6 --protocol mrp pair
atvremote --id A1B2C3D4E5F6 --protocol companion pair
```

Repeat pairing for each Apple TV, and repeat for any other supported protocol
shown by `scan` if pyatv reports it as pairable.

Quick verification:

```bash
atvremote --id A1B2C3D4E5F6 power_state
atvremote --id A1B2C3D4E5F6 app
atvremote --id A1B2C3D4E5F6 playing
```

### 2. Download The Project

```bash
git clone https://github.com/DennisFury/plex-session-bridge.git
cd plex-session-bridge
```

### 3. Install Python Dependencies

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

This installs `pyatv` as well as the bridge dependencies.

### 4. Configure Plex And Apple TVs

Copy the example config and edit it for your environment:

```bash
cp config.example.yaml config.yaml
```

The bridge reads `config.yaml` at runtime. `config.example.yaml` is only a
public template. `config.yaml` is intentionally ignored by git so it can contain
your private device IDs and network details.

Example with multiple Apple TVs:

```yaml
plex:
  url: "http://plex.example.test:32400"
  token_env: "PLEX_TOKEN"

server:
  host: "127.0.0.1"
  port: 8097

poll_interval_s: 5
max_poll_failures: 5
max_concurrent_devices: 2

devices:
  media_room:
    name: "Media Room"
    ip: "192.0.2.21"
    mac_address: "A1B2C3D4E5F6"
    plex_user: "plex-user"
    synthetic_client_id: "infuse-bridge-media-room"

  bedroom:
    name: "Bedroom"
    ip: "192.0.2.22"
    mac_address: "B2C3D4E5F6A1"
    plex_user: "plex-user"
    synthetic_client_id: "infuse-bridge-bedroom"
```

Each physical Apple TV should have a unique `synthetic_client_id`. Use stable
values and do not generate a new one for every movie.

### 5. Configure Secrets

You need a Plex authentication token for the Plex account that should own
playback history. Plex documents one way to find it here:
[Finding an authentication token / X-Plex-Token](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/).

Create a local environment file. Do not commit this file:

```bash
cp .env.example .env
```

Then edit `.env` with your Plex URL and Plex token.

The Plex user is determined by the token. The `plex_user` field is used for
matching and logging; it does not impersonate another Plex account.

### 6. Run Locally

```bash
set -a
. ./.env
set +a

.venv/bin/python -m uvicorn app.main:app \
  --host 127.0.0.1 \
  --port 8097 \
  --log-level warning \
  --no-access-log
```

Check health and state:

```bash
curl http://127.0.0.1:8097/health
curl http://127.0.0.1:8097/devices
curl http://127.0.0.1:8097/sessions
```

### 7. Install As A Service

For a system service, create `/etc/plex-infuse-bridge.env`:

```text
PLEX_URL=http://your-plex-server:32400
PLEX_TOKEN=your-plex-user-token
LOG_LEVEL=WARNING
```

Install and enable:

```bash
sudo install -m 644 systemd/plex-infuse-bridge.service /etc/systemd/system/plex-infuse-bridge.service
sudo systemctl daemon-reload
sudo systemctl enable --now plex-infuse-bridge.service
sudo systemctl status plex-infuse-bridge.service
```

The included systemd template assumes the project lives at
`/opt/plex-infuse-bridge` and runs as a `plexbridge` user. Edit the unit before
installing if your path or user is different.

## Finding Apple TV IDs

This project shells out to `atvremote` because that path has proven reliable
with current pyatv behavior.

Useful commands:

```bash
atvremote scan
atvremote --id A1B2C3D4E5F6 power_state
atvremote --id A1B2C3D4E5F6 app
atvremote --id A1B2C3D4E5F6 playing
```

Example outputs the parser expects:

```text
PowerState.On
```

```text
App: Infuse (com.firecore.infuse)
```

```text
  Media type: Video
Device state: Playing
       Title: Example Show - S1 ∙ E1 - Pilot
    Position: 120/1800s (6.7%)
      Repeat: Off
     Shuffle: Off
```

## Manual Plex Timeline POC

Before running the daemon, you can manually prove Plex accepts synthetic
timeline updates:

```bash
set -a
. ./.env
set +a

.venv/bin/python plex_session_poc.py \
  --rating-key 12345 \
  --state playing \
  --position 120 \
  --duration 1800 \
  --device-name "Media Room Infuse Bridge" \
  --client-id infuse-bridge-media-room \
  --user plex-user
```

The script prints whether `/status/sessions` and `plex.sessions()` see the
synthetic session.

Stop a test session:

```bash
.venv/bin/python plex_session_poc.py \
  --rating-key 12345 \
  --state stopped \
  --position 180 \
  --duration 1800 \
  --device-name "Media Room Infuse Bridge" \
  --client-id infuse-bridge-media-room
```

## Playback Registration API

Deep-link launchers usually know the exact Plex item being launched. Registering
that item avoids title matching and is the preferred path.

```bash
curl -X POST http://127.0.0.1:8097/playback/register \
  -H 'Content-Type: application/json' \
  -d '{
    "device": "media_room",
    "rating_key": "12345",
    "guid": "plex://movie/example",
    "title": "Example Movie",
    "duration_ms": 7200000,
    "media_part_key": "/library/parts/123/file.mkv",
    "filename": "Example Movie (2024).mkv",
    "plex_user": "plex-user",
    "source": "infuse_deeplink"
  }'
```

Registered metadata takes precedence over title matching.

## Systemd

Example unit files are provided in `systemd/`.

System service template:

```text
systemd/plex-infuse-bridge.service
```

User service template:

```text
systemd/plex-infuse-bridge.user.service
```

The install section above includes the standard system service commands. For
reference, the service environment file should look like this:

```text
PLEX_URL=http://your-plex-server:32400
PLEX_TOKEN=your-plex-user-token
LOG_LEVEL=WARNING
```

Then install and enable:

```bash
sudo install -m 644 systemd/plex-infuse-bridge.service /etc/systemd/system/plex-infuse-bridge.service
sudo systemctl daemon-reload
sudo systemctl enable --now plex-infuse-bridge.service
sudo systemctl status plex-infuse-bridge.service
```

## Logging

Default service logging is intentionally quiet:

```text
LOG_LEVEL=WARNING
```

Use `INFO` or `DEBUG` only when diagnosing reconciliation decisions.

## Development

Run tests:

```bash
.venv/bin/python -m pytest -q
```

Run syntax checks:

```bash
.venv/bin/python -m py_compile plex_session_poc.py app/*.py
```

## Current Limitations

- Runtime state is in memory. A future version should persist synthetic session
  state in SQLite for stronger restart recovery.
- Manual Infuse fallback matching is deterministic but intentionally limited.
  If multiple Plex items match, the bridge should observe only and not guess.
- Plex Dashboard may show the bridge host IP and imperfect bandwidth values for
  synthetic sessions.
- Tautulli is not integrated directly. It should observe Plex normally.
