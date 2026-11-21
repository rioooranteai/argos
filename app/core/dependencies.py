from fastapi import Depends, Request

from app.core import log_context
from app.core.errors import AuthenticationError, PermissionDenied
from app.core.rate_limit import limiter
from app.core.security import is_admin
from app.core.session import decode_session_token, session_token_from
from app.engines.chat_engine.engine import ChatEngine
from app.services.conversation.service import ConversationService
from app.services.library.service import LibraryService
from app.services.nl2sql.service import NL2SQLService
from app.services.notebook.service import NotebookService
from app.services.user.admin import AdminService
from app.services.user.model import CurrentUser, User
from app.services.voice.service import VoiceService

# Sesi hanya dari cookie HttpOnly (DESIGN_GROUP_D.md D1). Argos hanya dipakai lewat
# browser, jadi header ``Authorization: Bearer`` sengaja tidak diterima.


def user_from_token(request: Request, token: str | None) -> tuple[User, dict] | None:
    """User aktif + payload bila token sah; selain itu None. Tidak melempar error."""
    if not token:
        return None
    payload = decode_session_token(token)
    if payload is None:
        return None
    user = request.app.state.user_repo.get(payload.get("sub", ""))
    if user is None or not user.is_active:
        return None
    return user, payload


def get_current_user(request: Request) -> CurrentUser:
    """Sesi dari cookie HttpOnly; user harus ada & aktif. Header Bearer diabaikan."""
    token = session_token_from(request)
    if not token:
        raise AuthenticationError()

    payload = decode_session_token(token)
    if payload is None:
        raise AuthenticationError("Sesi tidak valid atau sudah berakhir.", code="INVALID_TOKEN")

    user = request.app.state.user_repo.get(payload.get("sub", ""))
    if user is None:
        raise AuthenticationError("Sesi tidak valid atau sudah berakhir.", code="INVALID_TOKEN")
    if not user.is_active:
        raise PermissionDenied("Akun Anda dinonaktifkan.", code="USER_INACTIVE")

    log_context.bind_request(user_id=user.id)
    # Batas umum per user untuk semua endpoint yang butuh login (D9).
    limiter.check("default", user.id)

    return CurrentUser(
        id=user.id,
        email=user.email,
        name=user.name or user.email,
        given_name=payload.get("given_name", ""),
        picture=user.picture or "",
        is_admin=is_admin(user.email),
    )


def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if not user.is_admin:
        raise PermissionDenied("Hanya admin yang dapat melakukan ini.")
    return user


def get_library_service(request: Request) -> LibraryService:
    return request.app.state.library_service


def get_chat_engine(request: Request) -> ChatEngine:
    return request.app.state.chat_engine


def get_nl2sql_service(request: Request) -> NL2SQLService:
    return request.app.state.nl2sql_service


def get_voice_service(request: Request) -> VoiceService:
    return request.app.state.voice_service


def get_conversation_service(request: Request) -> ConversationService:
    return request.app.state.conversation_service


def get_notebook_service(request: Request) -> NotebookService:
    return request.app.state.notebook_service


def get_admin_service(request: Request) -> AdminService:
    return request.app.state.admin_service
