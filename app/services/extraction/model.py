from typing import Literal

from pydantic import BaseModel, Field


class ExtractionResult(BaseModel):
    """Outcome of one document extraction run."""

    status: Literal["success", "failed"]
    document_id: str
    total_features_extracted: int = 0


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
