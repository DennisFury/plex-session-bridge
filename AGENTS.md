# Agent Guidance

This file is for AI assistants and maintainers working in this repository.

## Project Goal

Plex Infuse Bridge reports Infuse playback on Apple TV to Plex Media Server as
synthetic Plex timeline sessions. The core safety goal is to avoid reporting
unrelated Apple TV apps to Plex.

## Non-Negotiable Safety Rules

- Check Apple TV power state before app or playback state.
- If power is off, do not create or update a Plex session.
- Check active app before playback metadata.
- Only `Infuse` / `com.firecore.infuse` may enter the synthetic reporting path.
- Never report YouTube, Music, Netflix, Prime Video, or other apps to Plex.
- Never interfere with native Plex playback.
- Never write directly to Plex or Tautulli databases.
- Never commit secrets, real LAN details, Apple TV identifiers, public IPs, or
  household-specific config.

## Preferred Implementation Pattern

- Keep parsing logic in `app/apple_tv.py`.
- Keep Plex HTTP details in `app/plex.py`.
- Keep reconciliation decisions in `app/reconciler.py`.
- Add tests for every parser or state-machine change.
- Treat command failures as unknown, not as confirmed stop.
- Confirmed states, such as `PowerState.Off`, non-Infuse active app, and Infuse
  idle, should stop synthetic sessions.

## Public Repo Hygiene

Before preparing a commit, run:

```bash
git status --short
rg -n "<private-token-or-network-pattern>" .
.venv/bin/python -m pytest -q
```

Review any matches carefully. Documentation examples should use reserved
documentation IP ranges like `192.0.2.0/24`.
