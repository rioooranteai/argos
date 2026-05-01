from __future__ import annotations

import logging
import sqlite3

logger = logging.getLogger(__name__)

MIGRATIONS: list[tuple[int, str]] = [
    (1, """
        CREATE TABLE IF NOT EXISTS features (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id     TEXT NOT NULL,
            competitor_name TEXT NOT NULL,
            feature_name    TEXT NOT NULL,
            price           REAL,
            price_currency  TEXT,
            advantages      TEXT,
            disadvantages   TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_features_competitor ON features (competitor_name);
        CREATE INDEX IF NOT EXISTS idx_features_feature    ON features (feature_name);
        CREATE INDEX IF NOT EXISTS idx_features_document   ON features (document_id);
    """),
    (2, """
        CREATE TABLE IF NOT EXISTS conversations (
            id         TEXT PRIMARY KEY,
            user_id    TEXT NOT NULL,
            title      TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_conversations_user
            ON conversations (user_id, updated_at DESC);

        CREATE TABLE IF NOT EXISTS messages (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            role            TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
            content         TEXT NOT NULL,
            created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_messages_conversation
            ON messages (conversation_id, created_at);
    """),
    (3, """
        DROP TABLE IF EXISTS conversation_history;
    """),
    (4, """
        -- v4: Switch features schema to brand_name + product_name split,
        -- aligning with the new extraction prompt and CompetitorFeature model.
        -- Old data is dropped because the v1 column `competitor_name` cannot
        -- be deterministically split into (brand_name, product_name) without
        -- re-running extraction.
        DROP INDEX IF EXISTS idx_features_competitor;
        DROP INDEX IF EXISTS idx_features_feature;
        DROP INDEX IF EXISTS idx_features_document;
        DROP TABLE IF EXISTS features;

        CREATE TABLE features (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id     TEXT NOT NULL,
            brand_name      TEXT,
            product_name    TEXT NOT NULL,
            price           REAL,
            price_currency  TEXT,
            advantages      TEXT,
            disadvantages   TEXT
        );
        CREATE INDEX idx_features_brand    ON features (brand_name);
        CREATE INDEX idx_features_product  ON features (product_name);
        CREATE INDEX idx_features_document  ON features (document_id);
    """),
]


def run_migrations(conn: sqlite3.Connection) -> None:
    """Apply pending migrations. Safe to call on every startup."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version    INTEGER PRIMARY KEY,
            applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

    applied = {
        row[0]
        for row in conn.execute("SELECT version FROM schema_version").fetchall()
    }

    for version, sql in MIGRATIONS:
        if version in applied:
            continue
        logger.info(f"Applying migration v{version}...")
        conn.executescript(sql)
        conn.execute(
            "INSERT INTO schema_version (version) VALUES (?)", (version,)
        )
        conn.commit()
        logger.info(f"Migration v{version} applied.")
