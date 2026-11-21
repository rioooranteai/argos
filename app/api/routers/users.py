from dataclasses import asdict

from fastapi import APIRouter, Depends

from app.api.dependencies import get_current_user
from app.services.user.model import CurrentUser

router = APIRouter(prefix="/api/v1/users", tags=["users"])


@router.get("/me")
def get_me(current_user: CurrentUser = Depends(get_current_user)):
    return asdict(current_user)
