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
        """Cari user lewat ID akun Google; buat baru (ID UUID) atau perbarui profil +
        last_login_at. Tidak mengubah is_active. `new_user_id` hanya untuk test/seed."""

    @abstractmethod
    def get(self, user_id: str) -> User | None:
        """Ambil user berdasarkan id (UUID)."""

    @abstractmethod
    def list_all(self) -> list[User]:
        """Semua user, urut nama/email."""

    @abstractmethod
    def set_active(self, user_id: str, active: bool) -> bool: ...
