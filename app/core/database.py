import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

# Default location for the SQLite DB. Kept as a module constant so existing
# imports continue to work, but Database() now accepts an explicit path so
# tests and alternative deployments can override it.
DB_PATH = Path(__file__).resolve().parent.parent.parent / "competitor_data.db"


class Database:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or DB_PATH

    @contextmanager
    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def get_db(self) -> Generator:
        with self.get_connection() as conn:
            yield conn

    def init_db(self):
        """Membuat tabel SQL jika belum ada saat aplikasi pertama kali berjalan.

        Catatan migrasi: tabel `conversation_history` (single-row-per-session,
        JSON blob) dari versi sebelumnya digantikan oleh `conversations` +
        `messages`. Tabel lama di-drop di sini bila masih ada — datanya tidak
        dipertahankan karena formatnya rusak (lihat audit history).
        """
        with self.get_connection() as conn:
            # Aktifkan foreign key enforcement (off by default di SQLite).
            conn.execute("PRAGMA foreign_keys = ON")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS features (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    document_id TEXT NOT NULL,
                    competitor_name TEXT NOT NULL,
                    feature_name TEXT NOT NULL,
                    price REAL,          
                    advantages TEXT,             
                    disadvantages TEXT              
                )
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_competitor_name
                ON features (competitor_name)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_feature_name
                ON features (feature_name)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_document_id
                ON features (document_id)
            """)

            # Drop tabel lama (data corrupt karena bug serialization).
            conn.execute("DROP TABLE IF EXISTS conversation_history")

            # ── Multi-conversation schema ──────────────────────────────────
            # 1 user → N conversations → N messages
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id          TEXT PRIMARY KEY,
                    user_id     TEXT NOT NULL,
                    title       TEXT NOT NULL,
                    created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_conversations_user
                ON conversations (user_id, updated_at DESC)
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    role            TEXT NOT NULL CHECK (role IN ('user','assistant')),
                    content         TEXT NOT NULL,
                    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_conversation
                ON messages (conversation_id, created_at)
            """)

    def insert_feature(self, feature_dict: dict, document_id: str):
        """
        Menyimpan satu baris fitur kompetitor ke tabel SQL.
        feature_dict diharapkan berasal dari CompetitorFeature.model_dump().
        """
        with self.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO features (
                    document_id,
                    competitor_name,
                    feature_name,
                    price,
                    advantages,
                    disadvantages
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    feature_dict.get("competitor_name"),
                    feature_dict.get("feature_name"),
                    feature_dict.get("price"),
                    feature_dict.get("advantages"),
                    feature_dict.get("disadvantages"),
                ),
            )

    def insert_features_batch(self, features: list[dict], document_id: str):
        with self.get_connection() as conn:
            conn.executemany(
                """
                INSERT INTO features (
                    document_id, competitor_name, feature_name,
                    price, advantages, disadvantages
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        document_id,
                        f.get("competitor_name"),
                        f.get("feature_name"),
                        f.get("price"),
                        f.get("advantages"),
                        f.get("disadvantages"),
                    )
                    for f in features
                ]
            )


db = Database()
