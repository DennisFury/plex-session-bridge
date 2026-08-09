from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class PlexConfig:
    url: str
    token: str


@dataclass(frozen=True)
class DeviceConfig:
    key: str
    name: str
    ip: str | None
    mac_address: str
    plex_user: str
    synthetic_client_id: str


@dataclass(frozen=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8097


@dataclass(frozen=True)
class BridgeConfig:
    plex: PlexConfig
    devices: dict[str, DeviceConfig]
    server: ServerConfig
    poll_interval_s: float = 5.0
    max_poll_failures: int = 5
    max_concurrent_devices: int = 2


def _read_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return loaded


def load_config(path: str | os.PathLike[str] = "config.yaml") -> BridgeConfig:
    root = Path(path)
    _read_dotenv(Path(".env"))
    if not root.exists():
        raise RuntimeError(f"{root} is required; copy config.example.yaml to {root} and edit it")
    data = _load_yaml(root)

    plex_data = data.get("plex", {})
    token_env = plex_data.get("token_env", "PLEX_TOKEN")
    token = os.environ.get(token_env)
    if not token:
        raise RuntimeError(f"{token_env} is required")
    plex_url = os.environ.get("PLEX_URL") or plex_data.get("url")
    if not plex_url:
        raise RuntimeError("PLEX_URL or plex.url is required")

    devices = {}
    for key, item in (data.get("devices") or {}).items():
        devices[key] = DeviceConfig(
            key=key,
            name=item["name"],
            ip=item.get("ip"),
            mac_address=item["mac_address"],
            plex_user=item.get("plex_user", "plex-user"),
            synthetic_client_id=item.get("synthetic_client_id", f"infuse-bridge-{key}"),
        )

    server_data = data.get("server", {})
    server = ServerConfig(
        host=server_data.get("host", "127.0.0.1"),
        port=int(server_data.get("port", 8097)),
    )

    return BridgeConfig(
        plex=PlexConfig(url=plex_url, token=token),
        devices=devices,
        server=server,
        poll_interval_s=float(data.get("poll_interval_s", 5.0)),
        max_poll_failures=int(data.get("max_poll_failures", 5)),
        max_concurrent_devices=int(data.get("max_concurrent_devices", 2)),
    )
