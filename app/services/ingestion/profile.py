"""Document profile: what a document is, built once while it is processed.

The profile (type, issuer, main subjects, period, …) is the document-level context that the
individual sections lack. It is given to:
  - the extractor, with every section unit, so a "Processor" section of a laptop spec sheet is
    read as options of that laptop, not as separate products;
  - the router, as the list of sources in the notebook (what kind of documents exist);
  - the synthesizer, next to the source list (who published what, for which period).

A profile that cannot be built never stops processing: the pipeline continues without it.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from app.services.ingestion.model import Section
from app.tools.llm.base import BaseLLM

logger = logging.getLogger(__name__)

_PROMPT = (Path(__file__).resolve().parents[3] / "prompts" / "document_profile.md").read_text(encoding="utf-8")

DOCUMENT_TYPES = (
    "price_list", "product_spec_sheet", "product_terms", "product_brochure", "product_review",
    "comparison", "financial_statement", "earnings_release", "investor_presentation",
    "market_report", "company_report", "other",
)


class DocumentProfile(BaseModel):
    title: str = Field(description="The document's own title, or a short descriptive title.")
    document_type: str = Field(description="One of DOCUMENT_TYPES.")
    issuer: str | None = Field(default=None, description="Company or organisation that published the document.")
    subjects: list[str] = Field(default_factory=list,
                                description="Main products, product lines or companies the document is about.")
    period: str | None = Field(default=None, description="Date or reporting period the content refers to.")
    language: str | None = None
    has_product_prices: bool = Field(default=False,
                                     description="True if the document states prices or fees customers pay.")
    summary: str = Field(default="", description="One sentence: what the document contains.")

    def as_context(self) -> str:
        """Compact multi-line form used inside prompts."""
        lines = [f"Title: {self.title}", f"Type: {self.document_type}"]
        if self.issuer:
            lines.append(f"Issuer: {self.issuer}")
        if self.subjects:
            lines.append("About: " + "; ".join(self.subjects))
        if self.period:
            lines.append(f"Period: {self.period}")
        lines.append("States customer prices or fees: " + ("yes" if self.has_product_prices else "no"))
        if self.summary:
            lines.append(f"Summary: {self.summary}")
        return "\n".join(lines)

    def as_line(self) -> str:
        """One line used in source lists."""
        parts = [self.document_type]
        if self.issuer:
            parts.append(f"issuer {self.issuer}")
        if self.subjects:
            parts.append("about " + ", ".join(self.subjects[:5]))
        if self.period:
            parts.append(f"period {self.period}")
        parts.append("prices: " + ("yes" if self.has_product_prices else "no"))
        return "; ".join(parts)


def document_excerpt(sections: list[Section], max_chars: int) -> str:
    """The outline (all headings) plus the text from the start of the document, up to `max_chars`."""
    headings = [s.heading for s in sections if s.heading and s.heading.strip()]
    outline = "\n".join(f"- {h}" for h in dict.fromkeys(headings))[: max_chars // 4]
    budget = max_chars - len(outline)
    parts, used = [], 0
    for s in sections:
        block = f"## {s.heading or '(untitled)'}\n{s.text}"
        if used + len(block) > budget:
            parts.append(block[: max(0, budget - used)])
            break
        parts.append(block)
        used += len(block)
    return f"OUTLINE\n{outline}\n\nTEXT FROM THE START\n" + "\n\n".join(parts)


class DocumentProfiler:
    def __init__(self, llm: BaseLLM, max_chars: int) -> None:
        self._llm = llm
        self._max_chars = max_chars

    async def profile(self, file_name: str, sections: list[Section]) -> DocumentProfile | None:
        prompt = f"<<FILE NAME>>\n{file_name}\n<</FILE NAME>>\n\n<<DOCUMENT>>\n" \
                 f"{document_excerpt(sections, self._max_chars)}\n<</DOCUMENT>>"
        try:
            raw = await self._llm.ainvoke(prompt=prompt, system=_PROMPT)
            profile = DocumentProfile.model_validate(json.loads(_json_part(raw)))
        except (ValidationError, json.JSONDecodeError, ValueError) as e:
            logger.warning("Document profile for %s could not be read: %s", file_name, e)
            return None
        except Exception:
            # A failed profile never stops processing; extraction runs without the context.
            logger.warning("Document profile for %s failed.", file_name, exc_info=True)
            return None
        if profile.document_type not in DOCUMENT_TYPES:
            profile.document_type = "other"
        profile.subjects = profile.subjects[:8]
        return profile


def _json_part(raw: str) -> str:
    match = re.search(r"\{.*\}", raw, flags=re.S)
    if not match:
        raise ValueError("no JSON object in the profile answer")
    return match.group(0)
