import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from jose import jwt

from app.core.config import app_config, secrets
from app.core.errors import PermissionDenied
from app.core.oauth import oauth
from app.core.security import verify_google_identity

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
logger = logging.getLogger(__name__)


def create_jwt_token(user_data: dict) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=app_config.JWT_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_data["id"]),
        "email": user_data["email"],
        "name": user_data["name"],
        "given_name": user_data.get("given_name", ""),
        "picture": user_data.get("picture", ""),
        "exp": expire,
    }
    return jwt.encode(payload, secrets.SECRET_KEY, algorithm=app_config.JWT_ALGORITHM)


def _login_error(code: str) -> RedirectResponse:
    return RedirectResponse(url=f"/login?error={quote(code)}")


@router.get("/google/login")
async def google_login(request: Request):
    redirect_uri = request.url_for("google_callback")
    # `hd` hanya petunjuk untuk layar pilih akun Google; penegakan tetap di callback.
    return await oauth.google.authorize_redirect(
        request, redirect_uri, hd=secrets.allowed_domain or None
    )


@router.get("/google/callback", name="google_callback")
async def google_callback(request: Request):
    token = await oauth.google.authorize_access_token(request)
    google_user = token["userinfo"]

    try:
        verify_google_identity(google_user)
    except PermissionDenied as exc:
        logger.info("Login ditolak (%s) untuk %s", exc.code, google_user.get("email"))
        return _login_error(exc.code)

    user_repo = request.app.state.user_repo
    user = user_repo.upsert_on_login(
        google_sub=google_user["sub"],
        email=google_user["email"],
        name=google_user.get("name"),
        picture=google_user.get("picture"),
    )
    if not user.is_active:
        logger.info("Login ditolak (USER_INACTIVE) untuk %s", user.email)
        return _login_error("USER_INACTIVE")

    jwt_token = create_jwt_token({
        "id": user.id,
        "email": user.email,
        "name": user.name or user.email,
        "given_name": google_user.get("given_name", ""),
        "picture": user.picture or "",
    })

    # Catatan: token lewat query string adalah temuan audit poin 5 (kelompok D).
    return RedirectResponse(url=f"/?token={jwt_token}")
