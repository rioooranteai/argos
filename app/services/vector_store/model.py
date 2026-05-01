from pydantic import BaseModel, Field
from typing import Any

class SearchResult(BaseModel):
    ids: list[list[str]]
    documents: list[list[str]]
    metadatas: list[list[dict[str, Any]]]
    distances: list[list[float]] | None = None


class VectorStoreConfig(BaseModel):
    provider: str = Field(default="chroma", description="Nama provider vector store")
    collection_name: str = Field(default="competitor_knowledge")
    db_path: str | None = Field(default=None, description="Path penyimpanan (khusus provider lokal seperti Chroma)")