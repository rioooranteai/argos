from datetime import datetime, timedelta

from app.core.config import config
from app.core.oauth import oauth
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from jose import jwt

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def create_jwt_token(user_data: dict) -> str:
    expire = datetime.utcnow() + timedelta(minutes=config.jwt_expire_minutes)
    payload = {
        "sub": str(user_data["id"]),
        "email": user_data["email"],
        "name": user_data["name"],
        "given_name": user_data.get("given_name", ""),
        "picture": user_data.get("picture", ""),
        "exp": expire,
    }
    return jwt.encode(payload, config.secret_key, algorithm=config.jwt_algorithm)


@router.get("/google/login")
async def google_login(request: Request):
    redirect_uri = request.url_for("google_callback")
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/google/callback", name="google_callback")
async def google_callback(request: Request):
    token = await oauth.google.authorize_access_token(request)
    google_user = token["userinfo"]

    jwt_token = create_jwt_token({
        "id": google_user["sub"],
        "email": google_user["email"],
        "name": google_user["name"],
        "given_name": google_user.get("given_name", ""),
        "picture": google_user.get("picture", ""),
    })

    return RedirectResponse(url=f"/?token={jwt_token}")
