import logging
from urllib.parse import quote

from authlib.integrations.base_client.errors import OAuthError
from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import RedirectResponse

from app.api.dependencies import get_user_repo
from app.core.config import secrets
from app.core.errors import PermissionDenied, RateLimited
from app.core.oauth import oauth
from app.core.rate_limit import client_ip, limiter
from app.core.security import GMAIL_DOMAIN, verify_google_identity
from app.core.session import clear_session_cookie, create_session_token, set_session_cookie
from app.services.user.ports import BaseUserRepository

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
logger = logging.getLogger(__name__)


def _login_error(code: str) -> RedirectResponse:
    return RedirectResponse(url=f"/login?error={quote(code)}")


def _login_rate_limited(request: Request) -> RedirectResponse | None:
    """Sign-in attempt limit per IP (D9). The sign-in flow is a browser navigation → redirect, not JSON."""
    try:
        limiter.check("login", client_ip(request))
    except RateLimited:
        return _login_error("RATE_LIMITED")
    return None


@router.get("/google/login")
async def google_login(request: Request):
    if (blocked := _login_rate_limited(request)) is not None:
        return blocked
    redirect_uri = request.url_for("google_callback")
    # `hd` is only a hint for Google's account picker; it is enforced in the callback.
    # It is meant for Workspace domains, so it is not sent in personal Gmail mode.
    domain = secrets.allowed_domain
    hint = domain if domain and domain != GMAIL_DOMAIN else None
    return await oauth.google.authorize_redirect(request, redirect_uri, hd=hint)


@router.get("/google/callback", name="google_callback")
async def google_callback(
    request: Request, user_repo: BaseUserRepository = Depends(get_user_repo)
):
    if (blocked := _login_rate_limited(request)) is not None:
        return blocked
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError as exc:
        # Not a server bug: the user cancelled, Google blocked the app (e.g. consent screen in
        # "Testing" and the account is not a test user), or the state no longer matches
        # (Back button, two tabs, expired sign-in session). Send them back to the login page.
        code = "GOOGLE_ACCESS_DENIED" if exc.error == "access_denied" else "GOOGLE_SIGN_IN_FAILED"
        logger.info("Google sign-in did not complete (%s: %s)", exc.error, exc.description or "-")
        return _login_error(code)
    google_user = token["userinfo"]

    try:
        verify_google_identity(google_user)
    except PermissionDenied as exc:
        logger.info("Sign-in rejected (%s) for %s", exc.code, google_user.get("email"))
        return _login_error(exc.code)

    user = user_repo.upsert_on_login(
        google_sub=google_user["sub"],
        email=google_user["email"],
        name=google_user.get("name"),
        picture=google_user.get("picture"),
    )
    if not user.is_active:
        logger.info("Sign-in rejected (USER_INACTIVE) for %s", user.email)
        return _login_error("USER_INACTIVE")

    token = create_session_token(user.id, google_user.get("given_name", ""))
    # The token goes in an HttpOnly cookie, not in the URL (audit point 5, DESIGN_GROUP_D.md D1).
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    set_session_cookie(response, request, token)
    return response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Sign out (clear the session cookie)")
def logout(request: Request) -> Response:
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(response, request)
    return response
