"""Konfigurasi aplikasi Argos.

Aturan (lihat DESIGN_GROUP_A.md §13):

- ``Secrets``   — SATU-SATUNYA yang membaca ``.env``. Hanya nilai rahasia dan
                  kebijakan keamanan (siapa yang boleh login, siapa admin, CORS).
- ``Infra``     — nilai yang berbeda per mesin (lokasi data, device Docling).
                  Dibaca dari environment variable OS saja (diisi docker-compose),
                  TIDAK pernah dari ``.env``. Default-nya langsung jalan di lokal.
- ``AppConfig`` — semua nilai lain (provider, model, timeout, batas, concurrency)
                  sebagai konstanta di kode. Tidak bisa ditimpa lewat environment.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = PROJECT_ROOT / ".env"


class Secrets(BaseSettings):
    """Nilai rahasia & keamanan. Sumber: file ``.env`` (dan env OS)."""

    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    OPENAI_API_KEY: str = ""
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    SECRET_KEY: str = ""

    # Kebijakan keamanan
    ALLOWED_GOOGLE_DOMAIN: str = ""  # klaim `hd` Google Workspace yang boleh login
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
        """Nama field wajib yang masih kosong."""
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
    """Nilai infrastruktur per mesin. Sumber: environment variable OS saja."""

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
        """File yang menunggu diproses worker (nama UUID)."""
        return self.DATA_DIR / "queue"


@dataclass(frozen=True)
class AppConfig:
    """Konstanta aplikasi. Ubah di sini (kode), bukan lewat environment."""

    # ── Provider & model ─────────────────────────────────────────────
    LLM_PROVIDER: str = "openai"
    EMBEDDING_PROVIDER: str = "openai"
    OPENAI_LLM_MODEL: str = "gpt-5.4"
    OPENAI_VLM_MODEL: str = "gpt-5-mini"
    OPENAI_VOICE_MODEL: str = "gpt-4o-mini-tts"
    OPENAI_TRANSCRIBE_MODEL: str = "whisper-1"
    OPENAI_EXTRACTION_MODEL: str = "gpt-5.4-mini"
    OPENAI_TITLE_MODEL: str = "gpt-4o-mini"
    OPENAI_CHAT_MODEL: str = "gpt-5.4-mini"
    OPENAI_ROUTER_MODEL: str = "gpt-4o-mini"
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"
    OPENAI_EMBEDDING_CHUNK_SIZE: int = 400

    # ── Docling ──────────────────────────────────────────────────────
    DOCLING_NUM_THREADS: int = 4
    DOCLING_OCR: bool = False  # True hanya untuk PDF hasil scan (lebih lambat)
    DOCLING_CONCURRENCY: int = 1
    DOCLING_TIMEOUT_BASE: int = 30  # detik
    DOCLING_TIMEOUT_PER_PAGE: int = 3  # detik per halaman

    # ── Auth ─────────────────────────────────────────────────────────
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60
    SESSION_COOKIE_NAME: str = "argos_session"  # HttpOnly (DESIGN_GROUP_D.md D1)
    API_DOCS_ENABLED: bool = True  # /docs, /redoc, /openapi.json publik (D5, portofolio)

    # ── Library & notebook ───────────────────────────────────────────
    NOTEBOOK_MAX_SOURCES: int = 10
    UPLOAD_MAX_FILE_MB: int = 10
    UPLOAD_MAX_PAGES: int = 100
    UPLOAD_MAX_FILES_PER_BATCH: int = 5
    UPLOAD_MAX_BATCH_MB: int = 30
    UPLOAD_ALLOWED_EXTENSIONS: tuple[str, ...] = (".pdf", ".md")

    # ── Saran kemiripan saat upload (A §6.3, Tahap 3) ────────────────
    # Dikalibrasi pada data/eval_corpus: produk berbeda tertinggi 0,894; versi baru ≥ 0,913.
    SIMILARITY_THRESHOLD: float = 0.9
    SIMILARITY_MIN_SHINGLES: int = 200     # teks lebih sedikit (mis. PDF scan) → tanpa saran
    PENDING_UPLOAD_TTL_MINUTES: int = 60   # pilihan yang tidak diputuskan → file dihapus

    # ── Worker ───────────────────────────────────────────────────────
    # Naikkan saat prompt/chunker/model ingestion berubah (A §5 `pipeline_version`).
    PIPELINE_VERSION: str = "1"
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

    # ── Timeout (detik) ──────────────────────────────────────────────
    LLM_TIMEOUT_ROUTER: int = 10
    LLM_TIMEOUT_NL2SQL: int = 20
    LLM_TIMEOUT_CHAT: int = 60
    LLM_TIMEOUT_TITLE: int = 10
    SQL_EXEC_TIMEOUT: int = 5
    EMBED_TIMEOUT: int = 30
    EMBED_BATCH_SIZE: int = 100
    VISION_TIMEOUT: int = 45
    EXTRACTION_TIMEOUT: int = 60
    DOC_TOTAL_TIMEOUT: int = 1200
    CHAT_TOTAL_TIMEOUT: int = 90

    # ── Ekstraksi ────────────────────────────────────────────────────
    EXTRACTION_MIN_SECTION_TOKENS: int = 300
    EXTRACTION_MAX_UNIT_TOKENS: int = 4000

    # ── Voice ────────────────────────────────────────────────────────
    STT_MAX_MB: int = 25

    # ── Logging & observability (DESIGN_GROUP_C.md §7) ───────────────
    LOG_FORMAT: str = "json"          # "json" | "text" (text untuk dibaca saat dev lokal)
    LOG_PROMPTS: bool = False         # True: prompt & respons LLM ditulis ke log level DEBUG
    LLM_CALLS_RETENTION_DAYS: int = 90


secrets = Secrets()
infra = Infra()
app_config = AppConfig()


def validate_required_config() -> None:
    """Gagal start (fail-fast) jika nilai rahasia/keamanan wajib kosong."""
    missing = secrets.missing_required()
    if missing:
        raise RuntimeError(
            "Konfigurasi wajib di .env belum diisi: " + ", ".join(missing)
        )
