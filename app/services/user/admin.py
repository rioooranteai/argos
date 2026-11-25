"""User management by the admin."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.core.errors import NotFoundError, ValidationError
from app.core.security import is_admin
from app.services.library.ports import BaseLibraryRepository
from app.services.user.model import CurrentUser, User
from app.services.user.ports import BaseUserRepository

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
            raise NotFoundError("User not found.")
        if target.id == admin.id or is_admin(target.email):
            raise ValidationError("The admin cannot be deactivated.", code="CANNOT_DEACTIVATE_ADMIN")

        self._users.set_active(user_id, active)
        transferred = 0
        if not active:
            # The documents can still be managed (deleted/archived) by the admin.
            transferred = self._library.transfer_ownership(user_id, admin.id)
            logger.info(
                "User %s deactivated by %s; %d document(s) transferred.", target.email, admin.email, transferred
            )
        else:
            logger.info("User %s reactivated by %s.", target.email, admin.email)
        return DeactivationResult(user=self._users.get(user_id), documents_transferred=transferred)
