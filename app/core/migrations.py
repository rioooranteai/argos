"""Skema database Argos.

Skema lama (features tanpa versi, conversations tanpa notebook) dihapus total
(keputusan Q6, DESIGN_GROUP_A.md). Database baru berada di ``DATA_DIR/argos.db``
sehingga migrasi dimulai lagi dari baseline v1.
"""
from __future__ import annotations

import logging
import sqlite3

logger = logging.getLogger(__name__)

MIGRATIONS: list[tuple[int, str]] = [
    (1, """
        -- ── User ────────────────────────────────────────────────────────
        CREATE TABLE users (
            id             TEXT PRIMARY KEY,              -- Google `sub`
            email          TEXT NOT NULL UNIQUE,
            name           TEXT,
            picture        TEXT,
            is_active      INTEGER NOT NULL DEFAULT 1,
            created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_login_at  TIMESTAMP
        );

        -- ── Library ─────────────────────────────────────────────────────
        CREATE TABLE library_documents (
            id                 TEXT PRIMARY KEY,
            display_name       TEXT NOT NULL,
            owner_id           TEXT NOT NULL REFERENCES users(id),
            latest_version_id  TEXT,                       -- versi `ready` terbaru
            status             TEXT NOT NULL DEFAULT 'active'
                               CHECK (status IN ('active', 'archived')),
            created_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX idx_library_documents_name ON library_documents (display_name);

        CREATE TABLE document_versions (
            id                 TEXT PRIMARY KEY,
            document_id        TEXT NOT NULL REFERENCES library_documents(id) ON DELETE CASCADE,
            version_no         INTEGER NOT NULL,
            content_hash       TEXT NOT NULL,              -- SHA-256 byte file
            original_filename  TEXT NOT NULL,
            file_ext           TEXT NOT NULL,
            size_bytes         INTEGER NOT NULL,
            page_count         INTEGER,
            uploaded_by        TEXT NOT NULL REFERENCES users(id),
            uploaded_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            -- Versi = job (DESIGN_GROUP_B.md §3.1)
            stage              TEXT NOT NULL DEFAULT 'queued'
                               CHECK (stage IN ('queued', 'parsing', 'vision', 'indexing',
                                                'extracting', 'ready', 'failed', 'cancelled')),
            progress_done      INTEGER NOT NULL DEFAULT 0,
            progress_total     INTEGER NOT NULL DEFAULT 0,
            attempts           INTEGER NOT NULL DEFAULT 0,
            next_retry_at      TIMESTAMP,
            locked_until       TIMESTAMP,
            cancel_requested   INTEGER NOT NULL DEFAULT 0,
            vision_failed      INTEGER NOT NULL DEFAULT 0,
            pipeline_version   TEXT NOT NULL,
            error              TEXT,
            started_at         TIMESTAMP,
            finished_at        TIMESTAMP,
            UNIQUE (content_hash),                         -- kunci idempotensi
            UNIQUE (document_id, version_no)
        );
        CREATE INDEX idx_versions_document ON document_versions (document_id);
        CREATE INDEX idx_versions_stage    ON document_versions (stage, next_retry_at);

        CREATE TABLE sections (
            version_id    TEXT NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
            section_hash  TEXT NOT NULL,                   -- hash isi saja
            heading       TEXT,
            page_start    INTEGER,
            ord           INTEGER NOT NULL,
            PRIMARY KEY (version_id, section_hash)
        );

        CREATE TABLE features (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id      TEXT NOT NULL REFERENCES library_documents(id) ON DELETE CASCADE,
            version_id       TEXT NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
            section_hash     TEXT NOT NULL,
            section_heading  TEXT,
            page_number      INTEGER,
            brand_name       TEXT,
            product_name     TEXT NOT NULL,
            price            REAL,
            price_currency   TEXT,
            advantages       TEXT,
            disadvantages    TEXT
        );
        CREATE INDEX idx_features_version ON features (version_id);
        CREATE INDEX idx_features_brand   ON features (brand_name);
        CREATE INDEX idx_features_product ON features (product_name);

        -- ── Notebook ────────────────────────────────────────────────────
        CREATE TABLE notebooks (
            id          TEXT PRIMARY KEY,
            owner_id    TEXT NOT NULL REFERENCES users(id),
            title       TEXT NOT NULL,
            created_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at  TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX idx_notebooks_owner ON notebooks (owner_id, updated_at DESC);

        -- version_id / document_id tanpa CASCADE: versi atau dokumen yang masih
        -- dipakai notebook tidak bisa terhapus tanpa sengaja (A §6.6-6.7).
        CREATE TABLE notebook_sources (
            notebook_id  TEXT NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
            document_id  TEXT NOT NULL REFERENCES library_documents(id),
            version_id   TEXT NOT NULL REFERENCES document_versions(id),
            enabled      INTEGER NOT NULL DEFAULT 1,
            added_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (notebook_id, document_id)
        );
        CREATE INDEX idx_notebook_sources_version ON notebook_sources (version_id);

        -- ── Chat ────────────────────────────────────────────────────────
        -- notebook_id masih boleh NULL sampai rute chat pindah ke notebook
        -- (IMPLEMENTATION_PLAN_AB.md langkah 7.2); setelah itu diwajibkan di service.
        CREATE TABLE conversations (
            id           TEXT PRIMARY KEY,
            notebook_id  TEXT REFERENCES notebooks(id) ON DELETE CASCADE,
            user_id      TEXT NOT NULL,
            title        TEXT NOT NULL,
            created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX idx_conversations_user     ON conversations (user_id, updated_at DESC);
        CREATE INDEX idx_conversations_notebook ON conversations (notebook_id, updated_at DESC);

        CREATE TABLE messages (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id  TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            role             TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
            content          TEXT NOT NULL,
            created_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            source_snapshot  TEXT,                         -- JSON: version_id aktif
            citations        TEXT                          -- JSON
        );
        CREATE INDEX idx_messages_conversation ON messages (conversation_id, created_at);

        -- ── Cache AI (juga berfungsi sebagai checkpoint, B §9) ──────────
        CREATE TABLE vision_cache (
            image_hash   TEXT NOT NULL,
            model        TEXT NOT NULL,
            description  TEXT NOT NULL,
            created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (image_hash, model)
        );

        CREATE TABLE extraction_cache (
            unit_hash         TEXT NOT NULL,
            pipeline_version  TEXT NOT NULL,
            result_json       TEXT NOT NULL,
            created_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (unit_hash, pipeline_version)
        );
    """),
    (2, """
        -- Penghitung nomor versi yang tidak pernah turun: versi yang dihapus tidak
        -- membuat nomornya dipakai ulang, sehingga sitasi lama "v2" tetap berarti
        -- isi yang sama (DESIGN_GROUP_A.md §6.7).
        ALTER TABLE library_documents ADD COLUMN version_counter INTEGER NOT NULL DEFAULT 1;
        UPDATE library_documents SET version_counter = COALESCE(
            (SELECT MAX(version_no) FROM document_versions v WHERE v.document_id = library_documents.id),
            1
        );
    """),
    (3, """
        -- Statistik pemakaian ulang per versi (Tahap 3, IMPLEMENTATION_PLAN_AB.md §4):
        -- JSON {chunks, chunks_reused, units, units_cached, images, images_cached}.
        ALTER TABLE document_versions ADD COLUMN reuse_stats TEXT;
    """),
    (4, """
        -- Saran kemiripan saat upload (Tahap 3): sidik teks bottom-k per versi, dan
        -- upload yang menunggu keputusan user "versi baru" / "dokumen terpisah".
        ALTER TABLE document_versions ADD COLUMN fingerprint BLOB;

        CREATE TABLE pending_uploads (
            id                     TEXT PRIMARY KEY,
            user_id                TEXT NOT NULL REFERENCES users(id),
            original_filename      TEXT NOT NULL,
            file_ext               TEXT NOT NULL,
            size_bytes             INTEGER NOT NULL,
            content_hash           TEXT NOT NULL,
            page_count             INTEGER,
            fingerprint            BLOB,
            candidate_document_id  TEXT NOT NULL,         -- tanpa FK: kandidat boleh terhapus
            score                  REAL NOT NULL,
            created_at             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX idx_pending_uploads_created ON pending_uploads (created_at);
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

        conn.executescript(sql)
        conn.execute(
            "INSERT INTO schema_version (version) VALUES (?)", (version,)
        )
        conn.commit()
        logger.info(f"Migration v{version} applied.")
