"""SQLite adapter for FeatureRepository."""
from __future__ import annotations

from app.core.database import Database
from app.services.extraction.base.repository import BaseFeatureRepository


class SQLiteFeatureRepository(BaseFeatureRepository):
    def __init__(self, database: Database):
        self._db = database

    def insert_batch(self, features: list[dict], document_id: str) -> None:
        if not features:
            return
        self._db.insert_features_batch(features, document_id)
