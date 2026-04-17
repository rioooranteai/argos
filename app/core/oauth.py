from app.core.config import config
from authlib.integrations.starlette_client import OAuth

oauth = OAuth()
oauth.register(
    name="google",
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_id=config.google_client_id,
    client_secret=config.google_client_secret,
    client_kwargs={"scope": "openid email profile"}
)
