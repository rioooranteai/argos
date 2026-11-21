"""Observability: everything that lets us see what Argos is doing.

- ``logs/``      — log lines: setup (text/JSON), per-request/job context, request ID.
                   Always on, to stdout.
- ``ai_calls/``  — the AI call recorder: one ``llm_calls`` row per OpenAI call (model,
                   tokens, latency, status). Always on, Argos' own database; used by
                   /health/ready and the per-answer trace stored with each message.
- ``telemetry/`` — OpenTelemetry traces exported to Langfuse (or any OTLP backend), with
                   its own config. Optional: off until keys are set.

``ai_calls.recorder.track()`` is where they meet: one AI call becomes an ``llm_calls`` row
and a trace span, and ``trace_id`` ties both to the log lines.
"""
