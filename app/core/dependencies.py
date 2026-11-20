from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

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

# Header Bearer tetap diterima untuk alat non-browser (dan tombol "Authorize" di /docs).
# Browser memakai cookie HttpOnly (DESIGN_GROUP_D.md D1).
bearer = HTTPBearer(auto_error=False)


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


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> CurrentUser:
    """Sesi dari cookie (browser) atau header Bearer (alat lain); user harus ada & aktif."""
    token = session_token_from(request) or (credentials.credentials if credentials else None)
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
