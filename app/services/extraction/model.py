from dataclasses import dataclass


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
