"""Argos application configuration.

Rules (see DESIGN_GROUP_A.md §13):

- ``Secrets``   — the ONLY class that reads ``.env``. Only secrets and security
                  policy (who may sign in, who is admin, CORS).
- ``Infra``     — values that differ per machine (data location, Docling device).
                  Read from OS environment variables only (set by docker-compose),
                  NEVER from ``.env``. The defaults work out of the box locally.
- ``AppConfig`` — every other value (provider, model, timeouts, limits, concurrency)
                  as constants in code. Cannot be overridden through the environment.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = PROJECT_ROOT / ".env"


class Secrets(BaseSettings):
    """Secrets & security policy. Source: the ``.env`` file (and the OS environment)."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    OPENAI_API_KEY: str = ""
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    SECRET_KEY: str = ""

    # Security policy
    ALLOWED_GOOGLE_DOMAIN: str = ""  # Google Workspace `hd` claim allowed to sign in; "gmail.com" = personal Gmail
    ADMIN_EMAIL: str = ""
    ALLOWED_ORIGINS: str = "http://localhost:8000"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    @property
    def admin_email(self) -> str:
        return self.ADMIN_EMAIL.strip().lower()

    @property
    def allowed_domain(self) -> str:
        return self.ALLOWED_GOOGLE_DOMAIN.strip().lower()

    def missing_required(self) -> list[str]:
        """Names of required fields that are still empty."""
        required = (
            "OPENAI_API_KEY",
            "GOOGLE_CLIENT_ID",
            "GOOGLE_CLIENT_SECRET",
            "SECRET_KEY",
            "ALLOWED_GOOGLE_DOMAIN",
            "ADMIN_EMAIL",
            "ALLOWED_ORIGINS",
        )
        return [name for name in required if not str(getattr(self, name)).strip()]


class Infra(BaseSettings):
    """Per-machine infrastructure values. Source: OS environment variables only."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    DATA_DIR: Path = PROJECT_ROOT / "data"
    DOCLING_DEVICE: str = "auto"  # auto | cuda | cpu | mps

    @property
    def sqlite_path(self) -> Path:
        return self.DATA_DIR / "argos.db"

    @property
    def chroma_path(self) -> Path:
        return self.DATA_DIR / "chroma"

    @property
    def upload_queue_dir(self) -> Path:
        """Files waiting for the worker (UUID names)."""
        return self.DATA_DIR / "queue"


@dataclass(frozen=True)
class AppConfig:
    """Application constants. Change them here (in code), not through the environment."""

    # ── Tool providers (app/tools/factory.py picks the implementation) ──
    LLM_PROVIDER: str = "openai"
    EMBEDDING_PROVIDER: str = "openai"
    VECTOR_STORE_PROVIDER: str = "chroma"
    DOCUMENT_PARSER_PROVIDER: str = "docling"
    VISION_PROVIDER: str = "openai"
    EXTRACTION_PROVIDER: str = "pydantic_ai"
    STT_PROVIDER: str = "openai"
    TTS_PROVIDER: str = "openai"

    # ── Models ───────────────────────────────────────────────────────
    # Cheapest current models (OpenAI pricing page, 2026-11-21). gpt-6-luna reads images too.
    OPENAI_LLM_MODEL: str = "gpt-6-luna"
    OPENAI_VLM_MODEL: str = "gpt-6-luna"
    # No non-realtime replacement exists yet; gpt-4o-mini-tts shuts down on 2027-01-06.
    OPENAI_VOICE_MODEL: str = "gpt-4o-mini-tts"
    OPENAI_TRANSCRIBE_MODEL: str = "gpt-transcribe"
    OPENAI_EXTRACTION_MODEL: str = "gpt-6-luna"
    OPENAI_TITLE_MODEL: str = "gpt-6-luna"
    OPENAI_CHAT_MODEL: str = "gpt-6-luna"
    OPENAI_ROUTER_MODEL: str = "gpt-6-luna"
    # Reasoning effort per use (none | low | medium | high). gpt-6-luna is a reasoning model:
    # with an effort set, `temperature` is not sent (it only accepts the default). The
    # extraction agent needs "none" — function calling only works without reasoning.
    OPENAI_REASONING_EFFORT: dict[str, str] = field(default_factory=lambda: {
        "router": "none",
        "title": "none",
        "nl2sql": "none",
        "extraction": "none",
        "profile": "low",
        "chat": "low",
        "llm": "low",
        "vision": "low",
    })
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"
    OPENAI_EMBEDDING_CHUNK_SIZE: int = 400

    # ── Docling ──────────────────────────────────────────────────────
    DOCLING_NUM_THREADS: int = 4
    # Pages rendered and analysed together. Lower = less peak memory (Docling drops pages with
    # std::bad_alloc when memory runs out); higher = a little faster on a large machine.
    DOCLING_PAGE_BATCH_SIZE: int = 2
    # PDF backend used once more when the default one (docling-parse) runs out of memory on a
    # document: on some table-heavy PDFs it needs ~13 GB and drops most pages, pypdfium2 ~5 GB.
    # "pypdfium2" | "" (no second attempt: the job is retried with the same backend).
    DOCLING_FALLBACK_BACKEND: str = "pypdfium2"
    DOCLING_OCR: bool = False  # True only for scanned PDFs (slower)
    DOCLING_TIMEOUT_BASE: int = 30  # seconds
    # Seconds per A4-sized page (a larger page counts as several). A guard against a stuck parser,
    # not an estimate: a newspaper-format page (5.8 × A4, ~30 tables) took 106 s on a laptop.
    DOCLING_TIMEOUT_PER_PAGE: int = 20

    # ── Auth ─────────────────────────────────────────────────────────
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60
    SESSION_COOKIE_NAME: str = "argos_session"  # HttpOnly (DESIGN_GROUP_D.md D1)
    API_DOCS_ENABLED: bool = True  # /docs, /redoc, /openapi.json are public (D5, portfolio)

    # ── Rate limits per minute (DESIGN_GROUP_D.md D9) ────────────────
    RATE_LIMIT_WINDOW_SECONDS: int = 60
    RATE_LIMIT_CHAT: int = 20      # send & resend message (3–5 LLM calls per message)
    RATE_LIMIT_VOICE: int = 10     # STT & TTS
    RATE_LIMIT_UPLOAD: int = 10    # upload / new version / resolve pending
    RATE_LIMIT_LOGIN: int = 10     # per IP, before sign-in
    RATE_LIMIT_DEFAULT: int = 120  # every other endpoint (status polling ≈24/min)

    # ── Library & notebook ───────────────────────────────────────────
    NOTEBOOK_MAX_SOURCES: int = 10
    UPLOAD_MAX_FILE_MB: int = 10
    UPLOAD_MAX_PAGES: int = 100
    UPLOAD_MAX_FILES_PER_BATCH: int = 5
    UPLOAD_MAX_BATCH_MB: int = 30
    UPLOAD_ALLOWED_EXTENSIONS: tuple[str, ...] = (".pdf", ".md")

    # ── Similarity suggestion on upload (A §6.3, stage 3) ────────────
    # Calibrated on data/eval_corpus: different products peak at 0.894; new versions ≥ 0.913.
    SIMILARITY_THRESHOLD: float = 0.9
    SIMILARITY_MIN_SHINGLES: int = 200     # less text (e.g. a scanned PDF) → no suggestion
    PENDING_UPLOAD_TTL_MINUTES: int = 60   # choices left undecided → file is deleted

    # ── Worker ───────────────────────────────────────────────────────
    # Bump when the ingestion prompts/chunker/models change (A §5 `pipeline_version`).
    PIPELINE_VERSION: str = "3"  # 2: document profile + context for extraction; 3: model_code, product rules
    DOC_WORKERS: int = 2
    VERSION_LEASE_MINUTES: int = 10
    DOC_MAX_ATTEMPTS: int = 3
    DOC_RETRY_BACKOFF_MINUTES: tuple[int, ...] = (1, 5, 15)
    WORKER_POLL_SECONDS: float = 2.0
    WORKER_SHUTDOWN_GRACE: int = 20

    # ── Concurrency AI (global) ──────────────────────────────────────
    VISION_CONCURRENCY: int = 5
    EXTRACTION_CONCURRENCY: int = 3
    EMBED_CONCURRENCY: int = 2

    # ── NL2SQL ───────────────────────────────────────────────────────
    # CATALOG block (app/services/nl2sql/catalog.py): product names shown per document and the
    # size cap of the whole block (~4 chars per token → 3200 chars ≈ 800 tokens).
    NL2SQL_CATALOG_NAMES_PER_DOC: int = 30
    NL2SQL_CATALOG_MAX_CHARS: int = 3200
    # Second attempts when the first query is INVALID_QUESTION, fails, or finds 0 rows through a
    # text filter (LIKE). 0 = never retry.
    NL2SQL_MAX_RETRIES: int = 1

    # ── Timeouts (seconds) ───────────────────────────────────────────
    LLM_TIMEOUT_ROUTER: int = 10
    LLM_TIMEOUT_NL2SQL: int = 20
    LLM_TIMEOUT_CHAT: int = 60
    LLM_TIMEOUT_TITLE: int = 10
    LLM_TIMEOUT_PROFILE: int = 60
    SQL_EXEC_TIMEOUT: int = 5
    EMBED_TIMEOUT: int = 30
    EMBED_BATCH_SIZE: int = 100
    VISION_TIMEOUT: int = 45
    EXTRACTION_TIMEOUT: int = 60
    DOC_TOTAL_TIMEOUT: int = 1200
    CHAT_TOTAL_TIMEOUT: int = 90

    # ── Extraction ───────────────────────────────────────────────────
    # Document profile: how much of the document (from the start) the profiler reads.
    PROFILE_MAX_CHARS: int = 12000
    EXTRACTION_MIN_SECTION_TOKENS: int = 300
    # Text per extraction call. A dense price list holds ~1 item per 20 tokens: with 4000-token units
    # the model stopped early and whole pages had no rows (43-page list: 31/43 priced pages covered,
    # 42/43 at 1500). Small documents are one unit either way.
    EXTRACTION_MAX_UNIT_TOKENS: int = 1500

    # ── Voice ────────────────────────────────────────────────────────
    STT_MAX_MB: int = 25

    # ── Chat prompts ─────────────────────────────────────────────────
    # Time zone for the <<CURRENT_DATE>> block the router & synthesizer receive.
    APP_TIMEZONE: str = "Asia/Jakarta"
    APP_TIMEZONE_LABEL: str = "WIB"

    # ── Logging & observability (DESIGN_GROUP_C.md §7) ───────────────
    LOG_FORMAT: str = "auto"          # "auto" (text in a terminal, json otherwise) | "json" | "text"
    LOG_PROMPTS: bool = False         # True: LLM prompts & responses are logged at DEBUG
    LLM_CALLS_RETENTION_DAYS: int = 90


secrets = Secrets()
infra = Infra()
app_config = AppConfig()


def validate_required_config() -> None:
    """Fail fast on startup when a required secret/security value is empty."""
    missing = secrets.missing_required()
    if missing:
        raise RuntimeError(
            "Required settings missing in .env: " + ", ".join(missing)
        )
