"""Turns telemetry on at startup (called by ``app/bootstrap.py``).

``configure()`` installs a tracer provider that exports spans in the background
(BatchSpanProcessor) — exporting never blocks or fails a request. When telemetry is off
(no keys, or EXPORTER = "none") nothing is installed and the OpenTelemetry API stays a no-op.
"""
from __future__ import annotations

import logging

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SpanExporter
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

from app.core.telemetry.config import (
    TelemetryConfig,
    TelemetrySecrets,
    telemetry_config,
    telemetry_secrets,
)
from app.core.telemetry.context import ContextSpanProcessor

logger = logging.getLogger(__name__)

_provider: TracerProvider | None = None
_status = "disabled (not configured)"


def _exporter(cfg: TelemetryConfig, keys: TelemetrySecrets) -> tuple[SpanExporter | None, str]:
    kind = cfg.EXPORTER.lower()
    if kind == "none":
        return None, "disabled (EXPORTER = none)"
    if kind == "console":
        return ConsoleSpanExporter(), "enabled (console)"
    if kind == "otlp":
        if not keys.has_keys:
            return None, "disabled (LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY not set in .env)"
        exporter = OTLPSpanExporter(
            endpoint=cfg.otlp_traces_url(),
            headers=keys.otlp_headers(),
            timeout=cfg.EXPORT_TIMEOUT_SECONDS,
        )
        return exporter, f"enabled (otlp → {cfg.OTLP_ENDPOINT})"
    raise ValueError(f"Unknown telemetry exporter: '{cfg.EXPORTER}'")


def configure(cfg: TelemetryConfig | None = None, keys: TelemetrySecrets | None = None) -> bool:
    """Install the tracer provider. Returns whether telemetry is on."""
    global _provider, _status
    cfg = cfg or telemetry_config
    keys = keys or telemetry_secrets
    exporter, _status = _exporter(cfg, keys)
    if exporter is None:
        logger.info("Telemetry %s.", _status)
        return False
    provider = TracerProvider(
        resource=Resource.create({"service.name": cfg.SERVICE_NAME, "deployment.environment": cfg.ENVIRONMENT}),
        sampler=ParentBased(TraceIdRatioBased(cfg.SAMPLE_RATIO)),
    )
    provider.add_span_processor(ContextSpanProcessor(cfg.ENVIRONMENT))
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _provider = provider
    logger.info("Telemetry %s.", _status)
    return True


def shutdown() -> None:
    """Flush the spans still queued, then stop the exporter."""
    global _provider
    if _provider is not None:
        _provider.shutdown()
        _provider = None


def status() -> str:
    """For /health/ready: whether telemetry is on and where it sends spans."""
    return _status
