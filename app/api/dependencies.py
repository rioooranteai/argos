from collections.abc import Callable

from fastapi import Depends, Request

from app.core.errors import AuthenticationError, PermissionDenied
from app.core.observability.logs import context as log_context
from app.core.rate_limit import limiter
from app.core.security import is_admin
from app.core.session import decode_session_token, session_token_from
from app.engines.chat_engine.orchestrator import ChatOrchestrator
from app.services.conversation.service import ConversationService
from app.services.health.checker import HealthChecker
from app.services.library.service import LibraryService
from app.services.notebook.service import NotebookService
from app.services.user.admin import AdminService
from app.services.user.model import CurrentUser, User
from app.services.user.ports import BaseUserRepository
from app.services.voice.service import VoiceService

# The session comes only from the HttpOnly cookie (DESIGN_GROUP_D.md D1). Argos is only
# used from the browser, so the ``Authorization: Bearer`` header is deliberately not accepted.


# Every object a route needs is reached through one of these functions, so tests can
# swap any of them with ``app.dependency_overrides``. They read what bootstrap.py
# placed on ``app.state`` at startup; routers never read ``app.state`` themselves.


def get_user_repo(request: Request) -> BaseUserRepository:
    return request.app.state.user_repo


def get_health_checker(request: Request) -> HealthChecker:
    return request.app.state.health_checker


def user_from_token(request: Request, token: str | None) -> tuple[User, dict] | None:
    """The active user + payload when the token is valid; otherwise None. Never raises."""
    if not token:
        return None
    payload = decode_session_token(token)
    if payload is None:
        return None
    user = get_user_repo(request).get(payload.get("sub", ""))
    if user is None or not user.is_active:
        return None
    return user, payload


def get_current_user(
    request: Request, user_repo: BaseUserRepository = Depends(get_user_repo)
) -> CurrentUser:
    """Session from the HttpOnly cookie; the user must exist & be active. Bearer headers are ignored."""
    token = session_token_from(request)
    if not token:
        raise AuthenticationError()

    payload = decode_session_token(token)
    if payload is None:
        raise AuthenticationError("Your session is invalid or has expired.", code="INVALID_TOKEN")

    user = user_repo.get(payload.get("sub", ""))
    if user is None:
        raise AuthenticationError("Your session is invalid or has expired.", code="INVALID_TOKEN")
    if not user.is_active:
        raise PermissionDenied("Your account has been deactivated.", code="USER_INACTIVE")

    log_context.bind_request(user_id=user.id)
    # General per-user limit for every endpoint that needs a sign-in (D9).
    limiter.check("default", user.id)

    return CurrentUser(
        id=user.id,
        email=user.email,
        name=user.name or user.email,
        given_name=payload.get("given_name", ""),
        picture=user.picture or "",
        is_admin=is_admin(user.email),
    )


def rate_limit(group: str) -> Callable[..., None]:
    """FastAPI dependency: the `group` limit per signed-in user (DESIGN_GROUP_D.md D9)."""

    def _check(user: CurrentUser = Depends(get_current_user)) -> None:
        limiter.check(group, user.id)

    _check.__name__ = f"rate_limit_{group}"
    return _check


def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if not user.is_admin:
        raise PermissionDenied("Only the admin can do this.")
    return user


def get_library_service(request: Request) -> LibraryService:
    return request.app.state.library_service


def get_chat_orchestrator(request: Request) -> ChatOrchestrator:
    return request.app.state.chat_orchestrator


def get_voice_service(request: Request) -> VoiceService:
    return request.app.state.voice_service


def get_conversation_service(request: Request) -> ConversationService:
    return request.app.state.conversation_service


def get_notebook_service(request: Request) -> NotebookService:
    return request.app.state.notebook_service


def get_admin_service(request: Request) -> AdminService:
    return request.app.state.admin_service
