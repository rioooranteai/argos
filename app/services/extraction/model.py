from dataclasses import dataclass

from pydantic import BaseModel, Field


class CompetitorFeature(BaseModel):
    brand_name: str | None = Field(
        default=None,
        description=(
            "The manufacturer or brand that owns the product, "
            "as explicitly written in the text. "
            "Exclude the model name. Null if not determinable."
        ),
    )
    product_name: str = Field(
        description=(
            "The specific product or service variant name, "
            "excluding the brand prefix. "
            "Use the most specific name available from the text."
        ),
    )
    price: float | None = Field(
        default=None,
        description=(
            "Numeric value only of a direct user-facing price. "
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
    """LLM output: a feature + the label of its source section (DESIGN_GROUP_B.md §7)."""

    section_ref: str = Field(
        default="",
        description="Source section label, e.g. 'S1'. Must be one of the labels in the input.",
    )


@dataclass(frozen=True)
class FeatureRow:
    """A feature ready to store, tied to its document section (provenance)."""

    section_hash: str
    section_heading: str
    page_number: int | None
    brand_name: str | None
    product_name: str
    price: float | None
    price_currency: str | None
    advantages: str | None
    disadvantages: str | None
