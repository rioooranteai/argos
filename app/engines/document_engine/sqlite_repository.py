from __future__ import annotations

import logging
from dataclasses import dataclass

from app.core.database import Database

logger = logging.getLogger(__name__)


@dataclass
class FeatureRecord:
    competitor_name: str
    feature_name: str
    price: float | None
    price_currency: str | None
    advantages: str | None
    disadvantages: str | None


class SQLiteFeatureRepository:
    """Data access layer for competitor features table."""

    def __init__(self, database: Database) -> None:
        self._db = database

    def insert(self, feature: dict, document_id: str) -> None:
        with self._db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO features (
                    document_id, competitor_name, feature_name,
                    price, price_currency, advantages, disadvantages
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    feature.get("competitor_name"),
                    feature.get("feature_name"),
                    feature.get("price"),
                    feature.get("price_currency"),
                    feature.get("advantages"),
                    feature.get("disadvantages"),
                ),
            )
            logger.debug(f"Inserted feature for '{feature.get('competitor_name')}'")

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

    def get_by_competitor(self, competitor_name: str) -> list[dict]:
        with self._db.get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM features
                WHERE competitor_name = ?
                ORDER BY feature_name
                """,
                (competitor_name,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_by_document(self, document_id: str) -> list[dict]:
        with self._db.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM features WHERE document_id = ?",
                (document_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_by_document(self, document_id: str) -> int:
        with self._db.get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM features WHERE document_id = ?",
                (document_id,),
            )
            logger.info(f"Deleted {cursor.rowcount} features for document '{document_id}'")
            return cursor.rowcount