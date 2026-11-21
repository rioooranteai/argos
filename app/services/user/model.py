from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class User:
    id: str  # UUID (the Google account ID is in users.google_sub, used only for sign-in)
    email: str
    name: str | None
    picture: str | None
    is_active: bool
    created_at: datetime | None = None
    last_login_at: datetime | None = None


@dataclass(frozen=True)
class CurrentUser:
    """The signed-in user, from JWT verification + a database check."""

    id: str
    email: str
    name: str
    given_name: str
    picture: str
    is_admin: bool
