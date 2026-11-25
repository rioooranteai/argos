"""Cost of one AI call, from the prices in ``TelemetryConfig``.

Langfuse does not promise to price OTel-ingested generations itself, so Argos sends
``cost_details`` explicitly. A model without a configured price gets no cost (token usage
is still reported).
"""
from __future__ import annotations

from app.core.observability.telemetry.config import TelemetryConfig, telemetry_config


def token_cost(
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
    cfg: TelemetryConfig | None = None,
) -> dict[str, float] | None:
    cfg = cfg or telemetry_config
    price = cfg.MODEL_PRICES_USD_PER_1M_TOKENS.get(model)
    if price is None or (input_tokens is None and output_tokens is None):
        return None
    cost_in = (input_tokens or 0) * price[0] / 1_000_000
    cost_out = (output_tokens or 0) * price[1] / 1_000_000
    return {"input": cost_in, "output": cost_out, "total": cost_in + cost_out}


def audio_cost(model: str, seconds: float | None, cfg: TelemetryConfig | None = None) -> dict[str, float] | None:
    cfg = cfg or telemetry_config
    per_minute = cfg.STT_PRICE_USD_PER_MINUTE.get(model)
    if per_minute is None or seconds is None:
        return None
    return {"total": seconds / 60 * per_minute}


def character_cost(model: str, characters: int | None, cfg: TelemetryConfig | None = None) -> dict[str, float] | None:
    cfg = cfg or telemetry_config
    per_million = cfg.TTS_PRICE_USD_PER_1M_CHARS.get(model)
    if per_million is None or characters is None:
        return None
    return {"total": characters * per_million / 1_000_000}
