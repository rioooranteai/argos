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
    """Output LLM: feature + label bagian asalnya (DESIGN_GROUP_B.md §7)."""

    section_ref: str = Field(
        default="",
        description="Label bagian sumber, mis. 'S1'. Harus salah satu label di input.",
    )


@dataclass(frozen=True)
class FeatureRow:
    """Feature siap simpan, sudah terikat ke bagian dokumen (asal-usul)."""

    section_hash: str
    section_heading: str
    page_number: int | None
    brand_name: str | None
    product_name: str
    price: float | None
    price_currency: str | None
    advantages: str | None
    disadvantages: str | None
