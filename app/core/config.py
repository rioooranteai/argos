import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


class Config:
    # Provider selector
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "openai")
    EMBEDDING_PROVIDER: str = os.getenv("EMBEDDING_PROVIDER", "openai")

    # OpenAI
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_LLM_MODEL: str = os.getenv("OPENAI_LLM_MODEL", "gpt-4o-mini")
    OPENAI_EMBEDDING_MODEL: str = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    OPENAI_EMBEDDING_CHUNK_SIZE: int = int(os.getenv("OPENAI_EMBEDDING_CHUNK_SIZE", "512"))