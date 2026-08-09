from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.config import load_config
from app.logging_config import configure_logging
from app.models import Registration
from app.reconciler import Reconciler


class RegistrationRequest(BaseModel):
    device: str
    rating_key: str = Field(alias="rating_key")
    guid: str | None = None
    title: str | None = None
    duration_ms: int | None = None
    media_part_key: str | None = None
    filename: str | None = None
    plex_user: str | None = None
    source: str = "infuse_deeplink"
    ttl_s: int = 600


config = load_config()
configure_logging()
reconciler = Reconciler(config)
poller_task: asyncio.Task[None] | None = None


async def poll_forever() -> None:
    while True:
        await reconciler.reconcile_all()
        await asyncio.sleep(config.poll_interval_s)


@asynccontextmanager
async def lifespan(_: FastAPI):
    global poller_task
    poller_task = asyncio.create_task(poll_forever())
    try:
        yield
    finally:
        if poller_task:
            poller_task.cancel()
            try:
                await poller_task
            except asyncio.CancelledError:
                pass


app = FastAPI(title="Plex Infuse Bridge", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/devices")
async def devices() -> dict[str, object]:
    return {
        key: {
            "name": device.name,
            "ip": device.ip,
            "mac_address": device.mac_address,
            "plex_user": device.plex_user,
            "synthetic_client_id": device.synthetic_client_id,
            "last_result": reconciler.last_results.get(key),
        }
        for key, device in config.devices.items()
    }


@app.get("/devices/{device}")
async def device(device: str) -> dict[str, object]:
    if device not in config.devices:
        raise HTTPException(status_code=404, detail="unknown device")
    return {
        "device": config.devices[device],
        "last_result": reconciler.last_results.get(device),
        "registration": reconciler.registrations.get_active(device),
        "synthetic_session": reconciler.synthetic_sessions.get(device),
    }


@app.post("/devices/{device}/reconcile")
async def reconcile_device(device: str):
    if device not in config.devices:
        raise HTTPException(status_code=404, detail="unknown device")
    return await reconciler.reconcile_device(config.devices[device])


@app.get("/sessions")
async def sessions() -> dict[str, object]:
    plex_sessions = await asyncio.to_thread(reconciler.plex.sessions)
    return {
        "synthetic_sessions": reconciler.synthetic_sessions,
        "plex_sessions": plex_sessions,
    }


@app.post("/playback/register")
async def register(payload: RegistrationRequest) -> Registration:
    if payload.device not in config.devices:
        raise HTTPException(status_code=404, detail="unknown device")
    now = datetime.now(timezone.utc)
    registration = Registration(
        device=payload.device,
        rating_key=payload.rating_key,
        guid=payload.guid,
        title=payload.title,
        duration_ms=payload.duration_ms,
        media_part_key=payload.media_part_key,
        filename=payload.filename,
        plex_user=payload.plex_user or config.devices[payload.device].plex_user,
        source=payload.source,
        created_at=now,
        expires_at=now + timedelta(seconds=payload.ttl_s),
    )
    return reconciler.register(registration)


def main() -> None:
    import uvicorn

    uvicorn.run("app.main:app", host=config.server.host, port=config.server.port, reload=False)


if __name__ == "__main__":
    main()

