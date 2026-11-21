"""Telemetry configuration — kept apart from the application config (DESIGN_GROUP_F.md §4.6).

- ``TelemetrySecrets`` reads only the Langfuse keys from ``.env``. They are optional:
  without them telemetry is off and the app still starts.
- ``TelemetryConfig`` holds everything else as constants in code (exporter, endpoint,
  content capture, sampling, model prices). Change them here, not through the environment.

OpenTelemetry is only the transport (OTLP over HTTP); Langfuse is the destination. Pointing
``OTLP_ENDPOINT`` somewhere else (US region, self-hosted Langfuse, another OTLP backend) is
the only change needed to switch.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import PROJECT_ROOT


class TelemetrySecrets(BaseSettings):
    """Langfuse project keys (Settings → API keys in Langfuse). Source: ``.env``."""

    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""

    @property
    def has_keys(self) -> bool:
        return bool(self.LANGFUSE_PUBLIC_KEY.strip() and self.LANGFUSE_SECRET_KEY.strip())

    def otlp_headers(self) -> dict[str, str]:
        """Headers Langfuse's OTLP endpoint expects: Basic auth + ingestion version 4."""
        pair = f"{self.LANGFUSE_PUBLIC_KEY.strip()}:{self.LANGFUSE_SECRET_KEY.strip()}"
        return {
            "Authorization": "Basic " + base64.b64encode(pair.encode()).decode(),
            # Without it, directly ingested OTel data can show up in Langfuse ~10 min late.
            "x-langfuse-ingestion-version": "4",
        }


@dataclass(frozen=True)
class TelemetryConfig:
    # "otlp"    → send to OTLP_ENDPOINT (needs the keys in .env)
    # "console" → print spans to stdout (check locally without Langfuse)
    # "none"    → telemetry off
    EXPORTER: str = "otlp"

    # Langfuse Cloud EU. US: https://us.cloud.langfuse.com/api/public/otel
    # Self-hosted Langfuse (≥ 3.22): http://localhost:3000/api/public/otel
    OTLP_ENDPOINT: str = "https://cloud.langfuse.com/api/public/otel"
    EXPORT_TIMEOUT_SECONDS: int = 10

    SERVICE_NAME: str = "argos"
    ENVIRONMENT: str = "development"   # shown as langfuse.environment
    SAMPLE_RATIO: float = 1.0          # 1.0 = every chat / document gets a trace

    # Prompts, answers, SQL, retrieved chunks, image descriptions. Never: file/image/audio
    # bytes, cookies, tokens, API keys.
    CAPTURE_CONTENT: bool = True
    MAX_CONTENT_CHARS: int = 20_000    # per input/output field; longer text is cut

    # USD per 1M tokens: model → (input, output). Standard tier from OpenAI's pricing page
    # (2026-11-21); update when prices or models change. A model missing here still reports
    # token usage, just without cost. Cached input is not priced separately.
    MODEL_PRICES_USD_PER_1M_TOKENS: dict[str, tuple[float, float]] = field(default_factory=lambda: {
        "gpt-6-luna": (0.10, 0.50),
        "text-embedding-3-small": (0.02, 0.0),  # LangChain reports no embedding tokens yet
    })
    # Non-token pricing: transcription per audio minute, TTS per 1M characters.
    STT_PRICE_USD_PER_MINUTE: dict[str, float] = field(default_factory=lambda: {
        "gpt-transcribe": 0.0045,
    })
    # gpt-4o-mini-tts is priced per audio token, not per character → no cost shown for TTS.
    TTS_PRICE_USD_PER_1M_CHARS: dict[str, float] = field(default_factory=dict)

    def otlp_traces_url(self) -> str:
        return self.OTLP_ENDPOINT.rstrip("/") + "/v1/traces"


telemetry_secrets = TelemetrySecrets()
telemetry_config = TelemetryConfig()
