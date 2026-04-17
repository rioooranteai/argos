from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse
from jose import jwt
from datetime import datetime, timedelta
from app.core.oauth import oauth
from app.core.config import config
from app.services.user_service.user_service import UserService
from app.database.session import get_db
from sqlalchemy.orm import Session

router = APIRouter(prefix="/api/v1/auth", tags=['auth'])

def create_jwt_token(user_data: dict) -> str:
    expire = datetime.utcnow() + timedelta(minutes=config.jwt_expire_minutes)
    payload = {
        "sub": str(user_data['id']),
        "email": user_data['email'],
        "name": user_data['name'],
        "exp": expire
    }

    return jwt.encode(payload, config.secret_key, algorithm=config.jwt_algorithm)

@router.get("/google/login")
async def google_login(request: Request):
    redirect_uri = request.url_for("google_callback")
    return await oauth.google.authorize_redirect(request, redirect_uri)

@router.get("/google/callback", name="google_callback")
async def google_callback(
        request: Request,
        db: Session = Depends(get_db)
):
    token = await oauth.google.authorize_access_token(request)
    google_user = token['userinfo']

    user_svc = UserService(db)
    user = user_svc.get_or_create_from_google(
        google_id=google_user["sub"],
        email=google_user["email"],
        name=google_user["name"],
        picture=google_user.get("picture")
    )

    jwt_token = create_jwt_token({"id": user.id, "email": user.email, "name": user.name})

    return {"access_token": jwt_token, "token_type": "bearer", "user": {"email": user.email, "name": user.name}}

