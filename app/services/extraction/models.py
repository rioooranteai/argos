from pydantic import BaseModel, Field, field_validator


class CompetitorFeature(BaseModel):
    competitor_name: str = Field(
        description="Exact name of the competitor game or publisher"
    )
    feature_name: str = Field(
        description="Name of the feature, KPI, or capability (max 60 chars)"
    )
    price: float | None = Field(
        default=None,
        description=(
            "Direct user-facing price in USD as plain float. "
            "Example: 9.99, 29.0, 4.99. "
            "Null if no user-facing price is mentioned. "
            "Revenue figures and KPI metrics are NOT valid prices."
        )
    )
    advantages: str | None = Field(
        default=None,
        description="Positive aspects, strengths, or growth metrics as text"
    )
    disadvantages: str | None = Field(
        default=None,
        description="Negative aspects, weaknesses, or declining metrics as text"
    )

    @field_validator("price", mode="before")
    @classmethod
    def parse_price(cls, v):
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            cleaned = v.strip().replace("$", "").replace(",", "").replace(" ", "")
            try:
                return float(cleaned)
            except ValueError:
                return None
        return None

    @field_validator("competitor_name", "feature_name", mode="before")
    @classmethod
    def strip_whitespace(cls, v):
        if isinstance(v, str):
            return v.strip()
        return v


class ExtractionResult(BaseModel):
    status: str
    document_id: str
    total_features_extracted: int