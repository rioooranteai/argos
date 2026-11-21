"""Admin endpoints (one admin per deployment, set by ADMIN_EMAIL)."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.dependencies import get_admin_service, require_admin
from app.core.security import is_admin
from app.services.user.admin import AdminService
from app.services.user.model import CurrentUser, User

router = APIRouter(prefix="/api/v1/admin", tags=["Admin"])


class UserOut(BaseModel):
    id: str
    email: str
    name: str | None
    is_active: bool
    is_admin: bool
    last_login_at: datetime | None

    @classmethod
    def from_user(cls, u: User) -> "UserOut":
        return cls(id=u.id, email=u.email, name=u.name, is_active=u.is_active,
                   is_admin=is_admin(u.email), last_login_at=u.last_login_at)


class SetActiveRequest(BaseModel):
    is_active: bool


class SetActiveOut(UserOut):
    documents_transferred: int


@router.get("/users", summary="List users")
def list_users(
    _: CurrentUser = Depends(require_admin),
    svc: AdminService = Depends(get_admin_service),
) -> list[UserOut]:
    return [UserOut.from_user(u) for u in svc.list_users()]


@router.patch("/users/{user_id}", summary="Activate / deactivate a user")
def set_active(
    user_id: str,
    body: SetActiveRequest,
    admin: CurrentUser = Depends(require_admin),
    svc: AdminService = Depends(get_admin_service),
) -> SetActiveOut:
    result = svc.set_active(admin, user_id, body.is_active)
    return SetActiveOut(**UserOut.from_user(result.user).model_dump(),
                        documents_transferred=result.documents_transferred)
