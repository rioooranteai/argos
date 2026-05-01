from __future__ import annotations

import logging

from app.core.database import Database
from app.services.extraction.base.repository import BaseFeatureRepository

logger = logging.getLogger(__name__)


class SQLiteFeatureRepository(BaseFeatureRepository):
    def __init__(self, database: Database):
        self._db = database

    def insert_batch(self, features: list[dict], document_id: str) -> None:
        if not features:
            return
        with self._db.get_connection() as conn:
            conn.executemany(
                """
                INSERT INTO features (
                    document_id, competitor_name, feature_name,
                    price, price_currency, advantages, disadvantages
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        document_id,
                        f.get("competitor_name"),
                        f.get("feature_name"),
                        f.get("price"),
                        f.get("price_currency"),
                        f.get("advantages"),
                        f.get("disadvantages"),
                    )
                    for f in features
                ],
            )
            logger.info(f"Batch inserted {len(features)} features for document '{document_id}'")