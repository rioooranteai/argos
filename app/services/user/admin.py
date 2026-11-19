"""Pengelolaan user oleh admin (DESIGN_GROUP_A.md §4, tahap 2)."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.core.errors import NotFoundError, ValidationError
from app.core.security import is_admin
from app.infrastructure.interface.library_repository import BaseLibraryRepository
from app.infrastructure.interface.user_repository import BaseUserRepository
from app.services.user.model import CurrentUser, User

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeactivationResult:
    user: User
    documents_transferred: int


class AdminService:
    def __init__(self, users: BaseUserRepository, library: BaseLibraryRepository) -> None:
        self._users = users
        self._library = library

    def list_users(self) -> list[User]:
        return self._users.list_all()

    def set_active(self, admin: CurrentUser, user_id: str, active: bool) -> DeactivationResult:
        target = self._users.get(user_id)
        if target is None:
            raise NotFoundError("User tidak ditemukan.")
        if target.id == admin.id or is_admin(target.email):
            raise ValidationError("Admin tidak bisa dinonaktifkan.", code="CANNOT_DEACTIVATE_ADMIN")

        self._users.set_active(user_id, active)
        transferred = 0
        if not active:
            # Dokumen tetap bisa dikelola (dihapus/diarsipkan) oleh admin.
            transferred = self._library.transfer_ownership(user_id, admin.id)
            logger.info(
                "User %s dinonaktifkan oleh %s; %d dokumen dialihkan.", target.email, admin.email, transferred
            )
        else:
            logger.info("User %s diaktifkan kembali oleh %s.", target.email, admin.email)
        return DeactivationResult(user=self._users.get(user_id), documents_transferred=transferred)
