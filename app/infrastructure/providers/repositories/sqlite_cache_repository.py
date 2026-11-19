from __future__ import annotations

from app.core.database import Database
from app.infrastructure.interface.cache_repository import BaseCacheRepository


class SQLiteCacheRepository(BaseCacheRepository):
    def __init__(self, database: Database) -> None:
        self._db = database

    def get_vision(self, image_hash: str, model: str) -> str | None:
        with self._db.get_connection() as conn:
            row = conn.execute(
                "SELECT description FROM vision_cache WHERE image_hash = ? AND model = ?",
                (image_hash, model),
            ).fetchone()
        return row[0] if row else None

    def put_vision(self, image_hash: str, model: str, description: str) -> None:
        with self._db.get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO vision_cache (image_hash, model, description) VALUES (?, ?, ?)",
                (image_hash, model, description),
            )

    def get_extraction(self, unit_hash: str, pipeline_version: str) -> str | None:
        with self._db.get_connection() as conn:
            row = conn.execute(
                "SELECT result_json FROM extraction_cache WHERE unit_hash = ? AND pipeline_version = ?",
                (unit_hash, pipeline_version),
            ).fetchone()
        return row[0] if row else None

    def put_extraction(self, unit_hash: str, pipeline_version: str, result_json: str) -> None:
        with self._db.get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO extraction_cache (unit_hash, pipeline_version, result_json) "
                "VALUES (?, ?, ?)",
                (unit_hash, pipeline_version, result_json),
            )
