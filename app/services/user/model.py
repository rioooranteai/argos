from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class User:
    id: str  # UUID (ID akun Google ada di kolom users.google_sub, hanya untuk login)
    email: str
    name: str | None
    picture: str | None
    is_active: bool
    created_at: datetime | None = None
    last_login_at: datetime | None = None


@dataclass(frozen=True)
class CurrentUser:
    """User yang sedang login, hasil verifikasi JWT + cek database."""

    id: str
    email: str
    name: str
    given_name: str
    picture: str
    is_admin: bool
