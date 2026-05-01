from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

_env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(_env_path)


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_env_path,
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Provider selector
    LLM_PROVIDER: str = "openai"
    EMBEDDING_PROVIDER: str = "openai"

    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_LLM_MODEL: str = "gpt-5.4"
    OPENAI_VLM_MODEL: str = "gpt-5-mini"
    OPENAI_VOICE_MODEL: str = "gpt-4o-mini-tts"
    OPENAI_TRANSCRIBE_MODEL: str = "whisper-1"
    OPENAI_EXTRACTION_MODEL: str = "gpt-5.4-mini"
    OPENAI_TITLE_MODEL: str = "gpt-4o-mini"
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"
    OPENAI_EMBEDDING_CHUNK_SIZE: int = 400

    # Authentication
    google_client_id: str = ""
    google_client_secret: str = ""
    secret_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    # ALLOWED_ORIGINS
    ALLOWED_ORIGINS: str = "http://localhost:8000,http://localhost:3000"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    # Database
    DATABASE_URL: str = ""


config = Config()
