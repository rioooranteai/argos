from app.core.dependencies import get_current_user
from fastapi import APIRouter, Depends

router = APIRouter(prefix="/api/v1/users", tags=['users'])


@router.get("/me")
def get_me(current_user=Depends(get_current_user)):
    return current_user
