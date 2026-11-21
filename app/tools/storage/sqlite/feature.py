from __future__ import annotations

import json
import logging
import uuid

from app.core.database import Database
from app.services.extraction.ports import BaseFeatureRepository
from app.services.extraction.model import FeatureRow
from app.services.ingestion.model import Section

logger = logging.getLogger(__name__)


class SQLiteFeatureRepository(BaseFeatureRepository):
    def __init__(self, database: Database):
        self._db = database

    def publish_version(
        self,
        document_id: str,
        version_id: str,
        sections: list[Section],
        features: list[FeatureRow],
        reuse_stats: dict[str, int] | None = None,
    ) -> bool:
        with self._db.get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT cancel_requested FROM document_versions WHERE id = ?", (version_id,)
            ).fetchone()
            if row is None or row[0]:
                return False

            conn.execute("DELETE FROM features WHERE version_id = ?", (version_id,))
            conn.execute("DELETE FROM sections WHERE version_id = ?", (version_id,))
            conn.executemany(
                "INSERT OR IGNORE INTO sections (version_id, section_hash, heading, page_start, ord) "
                "VALUES (?, ?, ?, ?, ?)",
                [(version_id, s.section_hash, s.heading, s.page_start, s.ord) for s in sections],
            )
            conn.executemany(
                """
                INSERT INTO features (
                    id, document_id, version_id, section_hash, section_heading, page_number,
                    brand_name, product_name, price, price_currency, advantages, disadvantages
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(uuid.uuid4()), document_id, version_id, f.section_hash, f.section_heading, f.page_number,
                        f.brand_name, f.product_name, f.price, f.price_currency,
                        f.advantages, f.disadvantages,
                    )
                    for f in features
                ],
            )
            conn.execute(
                """
                UPDATE document_versions SET
                    stage = 'ready', error = NULL, locked_until = NULL, next_retry_at = NULL,
                    finished_at = CURRENT_TIMESTAMP, reuse_stats = ?
                WHERE id = ?
                """,
                (json.dumps(reuse_stats) if reuse_stats else None, version_id),
            )
            # The ready version with the highest number — an older version that finishes later
            # does not override a newer one.
            conn.execute(
                """
                UPDATE library_documents SET
                    latest_version_id = (
                        SELECT id FROM document_versions
                        WHERE document_id = ? AND stage = 'ready'
                        ORDER BY version_no DESC LIMIT 1
                    ),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (document_id, document_id),
            )
        return True

    def delete_version_content(self, version_id: str) -> None:
        with self._db.get_connection() as conn:
            conn.execute("DELETE FROM features WHERE version_id = ?", (version_id,))
            conn.execute("DELETE FROM sections WHERE version_id = ?", (version_id,))
