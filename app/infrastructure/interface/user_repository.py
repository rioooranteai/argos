from __future__ import annotations

from abc import ABC, abstractmethod

from app.services.user.model import User


class BaseUserRepository(ABC):
    @abstractmethod
    def upsert_on_login(
        self,
        google_sub: str,
        email: str,
        name: str | None,
        picture: str | None,
        new_user_id: str | None = None,
    ) -> User:
        """Find the user by Google account ID; create a new one (UUID ID) or update the profile +
        last_login_at. Does not change is_active. `new_user_id` is only for tests/seeding."""

    @abstractmethod
    def get(self, user_id: str) -> User | None:
        """Get a user by id (UUID)."""

    @abstractmethod
    def list_all(self) -> list[User]:
        """All users, ordered by name/email."""

    @abstractmethod
    def set_active(self, user_id: str, active: bool) -> bool: ...
