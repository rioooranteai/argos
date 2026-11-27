"""Prompt layout shared by the router and the synthesizer.

Every LLM prompt in the chat flow is ONE message made of named blocks, always in this order:

    <<HISTORY>>       recent conversation, cut per LLM in nodes/history.py (context, not instructions)
    <<SOURCES>>       the checked documents: name + profile (type, issuer, subjects, period)
    <<DATA>>          SQL rows + document chunks + source list (synthesizer only)
    <<INSTRUCTIONS>>  the rules from prompts/*.md
    <<QUESTION>>      the user's latest question
    <<CURRENT_DATE>>  today's date and time in APP_TIMEZONE

The instructions tell the model that HISTORY, SOURCES and DATA are data: any instruction that
appears inside them (e.g. written in an uploaded PDF) must be ignored.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import app_config
from app.services.ingestion.profile import DocumentProfile
from app.services.notebook.model import ActiveSource

_PROMPT_DIR = Path(__file__).resolve().parents[3] / "prompts"


def load_prompt(filename: str) -> str:
    path = _PROMPT_DIR / filename
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        raise FileNotFoundError(f"Prompt file not found: {path}") from None


def block(name: str, body: str) -> str:
    """``<<NAME>>`` … ``<</NAME>>``; an empty body is written as ``(none)``."""
    return f"<<{name}>>\n{body.strip() or '(none)'}\n<</{name}>>"


def _message_text(m) -> str:
    role = getattr(m, "type", "user")
    role = {"human": "user", "ai": "assistant"}.get(role, role)
    content = getattr(m, "content", "")
    if isinstance(content, list):
        content = " ".join(
            part.get("text", str(part)) if isinstance(part, dict) else str(part)
            for part in content
        )
    return f"{str(role).upper()}: {content}"


def history_text(messages: list) -> str:
    return "\n".join(_message_text(m) for m in messages)


def sources_text(sources: list[ActiveSource]) -> str:
    """One line per checked document: its name and, when known, its profile."""
    lines = []
    for s in sources:
        line = f"- {s.display_name}"
        if s.profile:
            try:
                line += " — " + DocumentProfile.model_validate(s.profile).as_line()
            except ValueError:
                pass
        lines.append(line)
    return "\n".join(lines)


def _tz():
    try:
        return ZoneInfo(app_config.APP_TIMEZONE)
    except ZoneInfoNotFoundError:  # no tz database on the host: Jakarta is a fixed UTC+7
        return timezone(timedelta(hours=7), app_config.APP_TIMEZONE_LABEL)


def current_date_text(now: datetime | None = None) -> str:
    """``Saturday, 21 November 2026, 19:40 WIB (Asia/Jakarta)`` — English, fixed format."""
    now = (now or datetime.now(timezone.utc)).astimezone(_tz())
    return (
        f"{now:%A}, {now.day} {now:%B %Y}, {now:%H:%M} "
        f"{app_config.APP_TIMEZONE_LABEL} ({app_config.APP_TIMEZONE})"
    )


def build_prompt(
    *, history: list, instructions: str, question: str,
    sources: list[ActiveSource] | None = None, data: str | None = None,
) -> str:
    """The full prompt in the fixed block order (``sources``/``data`` are left out when None)."""
    parts = [block("HISTORY", history_text(history))]
    if sources is not None:
        parts.append(block("SOURCES", sources_text(sources)))
    if data is not None:
        parts.append(block("DATA", data))
    parts += [
        block("INSTRUCTIONS", instructions),
        block("QUESTION", question),
        block("CURRENT_DATE", current_date_text()),
    ]
    return "\n\n".join(parts)
