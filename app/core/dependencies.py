from app.core.config import config
from app.core.database import db
from app.engines.chat_engine.engine import ChatEngine
from app.engines.document_engine.engine import DocumentProcessingEngine
from app.engines.document_engine.sqlite_repository import SQLiteFeatureRepository
from app.services.conversation.service import ConversationService
from app.services.conversation.sqlite_repository import SQLiteConversationRepository
from app.services.nl2sql.service import NL2SQLService
from app.services.voice.service import VoiceService
from fastapi import Depends, HTTPException, status
from fastapi import Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError

bearer = HTTPBearer()


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer)):
    try:
        payload = jwt.decode(
            credentials.credentials,
            config.secret_key,
            algorithms=[config.jwt_algorithm]
        )

        return payload
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def get_document_engine(request: Request) -> DocumentProcessingEngine:
    return request.app.state.document_engine


def get_chat_engine(request: Request) -> ChatEngine:
    return request.app.state.chat_engine


def get_nl2sql_service(request: Request) -> NL2SQLService:
    return request.app.state.nl2sql_service


def get_voice_service(request: Request) -> VoiceService:
    return request.app.state.voice_service


def get_conversation_service(request: Request) -> ConversationService:
    return request.app.state.conversation_service


def get_feature_repo() -> SQLiteFeatureRepository:
    return SQLiteFeatureRepository(db)


def get_conversation_repo() -> SQLiteConversationRepository:
    return SQLiteConversationRepository(db.db_path)
