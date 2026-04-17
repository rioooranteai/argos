from app.core.config import config
from app.engines.document_engine import DocumentProcessingEngine
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


def get_nl2sql_service(request: Request) -> NL2SQLService:
    return request.app.state.nl2sql_service


def get_voice_service(request: Request) -> VoiceService:
    return request.app.state.voice_service
