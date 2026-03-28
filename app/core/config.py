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
    OPENAI_LLM_MODEL: str = "gpt-5.4"
    OPENAI_VLM_MODEL: str = "gpt-5-mini"
    OPENAI_EXTRACTION_MODEL: str = "gpt-5.4-mini"
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"
    OPENAI_EMBEDDING_CHUNK_SIZE: int = 400