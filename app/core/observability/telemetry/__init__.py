"""Observability via OpenTelemetry (DESIGN_GROUP_F.md). Langfuse is only the destination.

- ``config``  — its own settings, separate from the app config (keys in .env, the rest in code)
- ``setup``   — install / shut down the tracer provider (called by bootstrap)
- ``spans``   — helpers to create spans with Langfuse-friendly attributes
- ``context`` — copies user/session/request context onto every span
"""
