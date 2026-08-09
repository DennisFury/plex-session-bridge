from __future__ import annotations

from datetime import datetime, timezone

from app.models import Registration


class RegistrationStore:
    def __init__(self) -> None:
        self._registrations: dict[str, Registration] = {}

    def upsert(self, registration: Registration) -> Registration:
        self._registrations[registration.device] = registration
        return registration

    def get_active(self, device: str) -> Registration | None:
        registration = self._registrations.get(device)
        if registration is None:
            return None
        if registration.expires_at <= datetime.now(timezone.utc):
            self._registrations.pop(device, None)
            return None
        return registration

    def clear(self, device: str) -> None:
        self._registrations.pop(device, None)

    def all(self) -> dict[str, Registration]:
        return dict(self._registrations)

