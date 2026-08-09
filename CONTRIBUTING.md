# Contributing

Thanks for considering a contribution.

This project is intentionally conservative because a bad implementation can
pollute Plex history or report unrelated Apple TV activity as Plex playback.

## Development Setup

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp config.example.yaml config.yaml
```

Set a local Plex token in `.env`:

```bash
cp .env.example .env
```

Then edit `.env` with local values.

Never commit `.env`, `config.yaml`, device inventories, logs, databases, or
anything containing Plex tokens, public IPs, LAN topology, Apple TV MAC
addresses, or usernames from a real household.

## Test Before Submitting

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m py_compile plex_session_poc.py app/*.py
```

Manual changes to reconciliation behavior should also be tested against:

- Apple TV powered off
- active app not Infuse
- Infuse playing
- Infuse paused
- Infuse idle
- transient `atvremote` failure
- native Plex app playback

## Design Rules

- Power state is the first gate.
- Active app is the second gate.
- Only Infuse may enter the synthetic Plex reporting path.
- Do not report YouTube, Music, Netflix, Prime Video, or other apps to Plex.
- Do not interfere with native Plex sessions.
- Do not write directly to Plex or Tautulli databases.
- Prefer exact registered Plex identity over title matching.
- Never guess silently when media matching is ambiguous.

## Pull Requests

Keep changes focused. Include tests for parsers, state transitions, and failure
behavior whenever practical.
