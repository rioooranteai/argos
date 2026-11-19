from __future__ import annotations

from abc import ABC, abstractmethod

from app.services.user.model import User


class BaseUserRepository(ABC):
    @abstractmethod
    def upsert_on_login(self, user_id: str, email: str, name: str | None, picture: str | None) -> User:
        """Buat user baru atau perbarui profil + last_login_at. Tidak mengubah is_active."""

    @abstractmethod
    def get(self, user_id: str) -> User | None:
        """Ambil user berdasarkan id (Google `sub`)."""

    @abstractmethod
    def list_all(self) -> list[User]:
        """Semua user, urut nama/email."""

    @abstractmethod
    def set_active(self, user_id: str, active: bool) -> bool: ...
