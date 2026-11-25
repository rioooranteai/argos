"""Extraction contract: turns document text into structured product features."""
from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, Field


class CompetitorFeature(BaseModel):
    brand_name: str | None = Field(
        default=None,
        description=(
            "The company that makes, issues or provides the product, as written in the text "
            "or as the document's issuer. Never the model name, a payment network or a partner. "
            "Null if not determinable."
        ),
    )
    product_name: str = Field(
        description=(
            "The specific product or service variant name, excluding the brand prefix: "
            "model name plus variant (e.g. from a table grouped by model). "
            "Not a component, option or category word."
        ),
    )
    model_code: str | None = Field(
        default=None,
        description=(
            "The product's model number, part number, SKU or product code exactly as written "
            "(e.g. 'XR-200-B'), if the text gives one for this product. Null if none."
        ),
    )
    price: float | None = Field(
        default=None,
        description=(
            "Numeric value only of the price a customer pays for the product, including a "
            "recurring annual/membership/subscription fee (0 if stated as free). "
            "No currency symbols. Null if not mentioned."
        ),
    )
    price_currency: str | None = Field(
        default=None,
        description=(
            "ISO 4217 currency code (e.g. USD, IDR, EUR, GBP, SGD). "
            "Null if no currency indicator exists near the price."
        ),
    )
    advantages: str | None = Field(
        default=None,
        description=(
            "Explicit positive facts stated in the text. "
            "Include exact numeric values when present. "
            "Null if none stated."
        ),
    )
    disadvantages: str | None = Field(
        default=None,
        description=(
            "Explicit negative facts stated in the text. "
            "Include exact numeric values when present. "
            "Null if none stated."
        ),
    )


class ExtractedFeature(CompetitorFeature):
    """LLM output: a feature + the label of its source section."""

    section_ref: str = Field(
        default="",
        description="Source section label, e.g. 'S1'. Must be one of the labels in the input.",
    )


class ExtractionError(Exception):
    """Base exception for every extraction error."""


class ExtractionAgentError(ExtractionError):
    """Failed while running the extraction agent."""


class BaseExtractor(ABC):
    @abstractmethod
    async def extract(self, text: str) -> list[ExtractedFeature]:
        """
        Takes the text of one extraction unit (sections labelled S1, S2, …) and
        returns the features found in it, each with the label of its section.
        """
