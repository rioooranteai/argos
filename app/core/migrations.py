"""Argos database schema.

The old schema (features without versions, conversations without notebooks) was
dropped entirely (decision Q6, DESIGN_GROUP_A.md). The new database lives in
``DATA_DIR/argos.db``, so migrations start again from a v1 baseline.
"""
from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable

logger = logging.getLogger(__name__)

# One migration = an SQL script, or a Python function for changes that cannot be
# written as plain SQL (e.g. generating UUIDs, rebuilding tables).
Migration = str | Callable[[sqlite3.Connection], None]

MIGRATIONS: list[tuple[int, Migration]] = [
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
            latest_version_id  TEXT,                       -- latest `ready` version
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
            content_hash       TEXT NOT NULL,              -- SHA-256 of the file bytes
            original_filename  TEXT NOT NULL,
            file_ext           TEXT NOT NULL,
            size_bytes         INTEGER NOT NULL,
            page_count         INTEGER,
            uploaded_by        TEXT NOT NULL REFERENCES users(id),
            uploaded_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            -- Version = job (DESIGN_GROUP_B.md §3.1)
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
            UNIQUE (content_hash),                         -- idempotency key
            UNIQUE (document_id, version_no)
        );
        CREATE INDEX idx_versions_document ON document_versions (document_id);
        CREATE INDEX idx_versions_stage    ON document_versions (stage, next_retry_at);

        CREATE TABLE sections (
            version_id    TEXT NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
            section_hash  TEXT NOT NULL,                   -- hash of the content only
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

        -- version_id / document_id without CASCADE: a version or document still
        -- used by a notebook cannot be deleted by accident (A §6.6-6.7).
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
        -- notebook_id may still be NULL until the chat routes move to notebooks
        -- (IMPLEMENTATION_PLAN_AB.md step 7.2); after that the service requires it.
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
            source_snapshot  TEXT,                         -- JSON: active version_id
            citations        TEXT                          -- JSON
        );
        CREATE INDEX idx_messages_conversation ON messages (conversation_id, created_at);

        -- ── AI cache (also works as a checkpoint, B §9) ─────────────────
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
        -- A version number counter that never goes down: a deleted version's number
        -- is never reused, so an old "v2" citation always means the same content
        -- (DESIGN_GROUP_A.md §6.7).
        ALTER TABLE library_documents ADD COLUMN version_counter INTEGER NOT NULL DEFAULT 1;
        UPDATE library_documents SET version_counter = COALESCE(
            (SELECT MAX(version_no) FROM document_versions v WHERE v.document_id = library_documents.id),
            1
        );
    """),
    (3, """
        -- Reuse statistics per version (stage 3, IMPLEMENTATION_PLAN_AB.md §4):
        -- JSON {chunks, chunks_reused, units, units_cached, images, images_cached}.
        ALTER TABLE document_versions ADD COLUMN reuse_stats TEXT;
    """),
    (4, """
        -- Similarity suggestion on upload (stage 3): a bottom-k text fingerprint per
        -- version, and uploads waiting for the user's "new version" / "separate document" choice.
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
            candidate_document_id  TEXT NOT NULL,         -- no FK: the candidate may be deleted
            score                  REAL NOT NULL,
            created_at             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX idx_pending_uploads_created ON pending_uploads (created_at);
    """),
    (5, """
        -- Group C (DESIGN_GROUP_C.md §4, §7).
        -- Failed messages: a user message that got no answer is marked `failed`,
        -- is left out of the LLM history, and can be resent.
        ALTER TABLE messages ADD COLUMN status TEXT NOT NULL DEFAULT 'ok'
            CHECK (status IN ('ok', 'failed'));
        ALTER TABLE messages ADD COLUMN error_code TEXT;
        -- Trace per answer (JSON, assistant messages only): route, SQL, chunks, timings, issues.
        ALTER TABLE messages ADD COLUMN trace TEXT;

        -- One row per OpenAI call. No prompts / document content.
        CREATE TABLE llm_calls (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            ts             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            purpose        TEXT NOT NULL,   -- router|nl2sql|synthesizer|title|vision|extraction|embedding|stt|tts
            model          TEXT NOT NULL,
            input_tokens   INTEGER,
            output_tokens  INTEGER,
            latency_ms     INTEGER NOT NULL,
            status         TEXT NOT NULL CHECK (status IN ('ok', 'error')),
            error_code     TEXT,
            request_id     TEXT,
            version_id     TEXT,            -- no FK: the record stays when the version is deleted
            message_id     INTEGER          -- ID of the triggering user message
        );
        CREATE INDEX idx_llm_calls_ts      ON llm_calls (ts);
        CREATE INDEX idx_llm_calls_message ON llm_calls (message_id);
    """),
]


# ── v6: every ID is a UUID (DESIGN_GROUP_D.md D10) ────────────────────────────

# Columns that refer to users.id (with or without an FK).
_USER_REFERENCES = (
    ("library_documents", "owner_id"),
    ("document_versions", "uploaded_by"),
    ("notebooks", "owner_id"),
    ("conversations", "user_id"),
    ("pending_uploads", "user_id"),
)


def _rebuild(conn: sqlite3.Connection, table: str, create_sql: str, columns: list[str],
             rows: list[tuple], indexes: tuple[str, ...] = ()) -> None:
    """Rebuild `table` with a new structure and fill it with `rows` (in `columns` order)."""
    conn.execute(create_sql.replace(f"CREATE TABLE {table} ", f"CREATE TABLE {table}__new ", 1))
    placeholders = ", ".join("?" for _ in columns)
    conn.executemany(
        f"INSERT INTO {table}__new ({', '.join(columns)}) VALUES ({placeholders})", rows
    )
    conn.execute(f"DROP TABLE {table}")
    conn.execute(f"ALTER TABLE {table}__new RENAME TO {table}")
    for index_sql in indexes:
        conn.execute(index_sql)


def _v6_uuid_ids(conn: sqlite3.Connection) -> None:
    import uuid

    def new_id() -> str:
        return str(uuid.uuid4())

    # ── users: id = new UUID, the Google ID moves to google_sub ────────
    old_users = conn.execute(
        "SELECT id, email, name, picture, is_active, created_at, last_login_at FROM users"
    ).fetchall()
    user_map = {row[0]: new_id() for row in old_users}
    _rebuild(conn, "users", """
        CREATE TABLE users (
            id             TEXT PRIMARY KEY,              -- UUID
            google_sub     TEXT UNIQUE,                   -- Google account ID; only for sign-in
            email          TEXT NOT NULL UNIQUE,
            name           TEXT,
            picture        TEXT,
            is_active      INTEGER NOT NULL DEFAULT 1,
            created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_login_at  TIMESTAMP
        )""",
        ["id", "google_sub", "email", "name", "picture", "is_active", "created_at", "last_login_at"],
        [(user_map[r[0]], r[0], *r[1:]) for r in old_users],
    )
    for table, column in _USER_REFERENCES:
        conn.executemany(
            f"UPDATE {table} SET {column} = ? WHERE {column} = ?",
            [(new, old) for old, new in user_map.items()],
        )

    # ── messages: id = UUID, order via seq (not exposed by the API) ────
    old_messages = conn.execute(
        """SELECT id, conversation_id, role, content, created_at, source_snapshot, citations,
                  status, error_code, trace FROM messages ORDER BY id"""
    ).fetchall()
    message_map = {row[0]: new_id() for row in old_messages}
    _rebuild(conn, "messages", """
        CREATE TABLE messages (
            id               TEXT PRIMARY KEY,             -- UUID
            seq              INTEGER NOT NULL UNIQUE,      -- insert order; internal
            conversation_id  TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            role             TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
            content          TEXT NOT NULL,
            created_at       TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            source_snapshot  TEXT,
            citations        TEXT,
            status           TEXT NOT NULL DEFAULT 'ok' CHECK (status IN ('ok', 'failed')),
            error_code       TEXT,
            trace            TEXT
        )""",
        ["id", "seq", "conversation_id", "role", "content", "created_at", "source_snapshot",
         "citations", "status", "error_code", "trace"],
        [(message_map[r[0]], r[0], *r[1:]) for r in old_messages],
        ("CREATE INDEX idx_messages_conversation ON messages (conversation_id, seq)",),
    )

    # ── llm_calls: id = UUID, message_id follows the message UUID ──────
    old_calls = conn.execute(
        """SELECT id, ts, purpose, model, input_tokens, output_tokens, latency_ms, status,
                  error_code, request_id, version_id, message_id FROM llm_calls ORDER BY id"""
    ).fetchall()
    _rebuild(conn, "llm_calls", """
        CREATE TABLE llm_calls (
            id             TEXT PRIMARY KEY,   -- UUID
            seq            INTEGER NOT NULL UNIQUE,
            ts             TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            purpose        TEXT NOT NULL,
            model          TEXT NOT NULL,
            input_tokens   INTEGER,
            output_tokens  INTEGER,
            latency_ms     INTEGER NOT NULL,
            status         TEXT NOT NULL CHECK (status IN ('ok', 'error')),
            error_code     TEXT,
            request_id     TEXT,
            version_id     TEXT,
            message_id     TEXT                -- UUID of the triggering user message; no FK
        )""",
        ["id", "seq", "ts", "purpose", "model", "input_tokens", "output_tokens", "latency_ms",
         "status", "error_code", "request_id", "version_id", "message_id"],
        [(new_id(), r[0], *r[1:11], message_map.get(r[11])) for r in old_calls],
        ("CREATE INDEX idx_llm_calls_ts      ON llm_calls (ts)",
         "CREATE INDEX idx_llm_calls_message ON llm_calls (message_id)"),
    )

    # ── features: id = UUID ─────────────────────────────────────────────
    feature_columns = ["document_id", "version_id", "section_hash", "section_heading",
                       "page_number", "brand_name", "product_name", "price", "price_currency",
                       "advantages", "disadvantages"]
    old_features = conn.execute(
        f"SELECT {', '.join(feature_columns)} FROM features ORDER BY id"
    ).fetchall()
    _rebuild(conn, "features", """
        CREATE TABLE features (
            id               TEXT PRIMARY KEY,   -- UUID
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
        )""",
        ["id", *feature_columns],
        [(new_id(), *r) for r in old_features],
        ("CREATE INDEX idx_features_version ON features (version_id)",
         "CREATE INDEX idx_features_brand   ON features (brand_name)",
         "CREATE INDEX idx_features_product ON features (product_name)"),
    )


MIGRATIONS.append((6, _v6_uuid_ids))

# v7: the last opened notebook is stored on the server, not in localStorage (D8).
MIGRATIONS.append((7, """
    ALTER TABLE notebooks ADD COLUMN last_opened_at TIMESTAMP;
"""))


def run_migrations(conn: sqlite3.Connection, migrations: list[tuple[int, Migration]] | None = None) -> None:
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

    for version, migration in migrations if migrations is not None else MIGRATIONS:
        if version in applied:
            continue

        if callable(migration):
            _run_python_migration(conn, version, migration)
        else:
            conn.executescript(migration)
            conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)", (version,)
            )
            conn.commit()
        logger.info("Migration v%s applied.", version)


def _run_python_migration(
    conn: sqlite3.Connection, version: int, migration: Callable[[sqlite3.Connection], None]
) -> None:
    """One transaction; foreign keys are off while tables are rebuilt.

    The official SQLite procedure for changing a table's structure (create the new
    table → copy → drop the old one → rename). Before commit, ``foreign_key_check``
    must be empty; if not, or if the migration raises, every change is rolled back.
    """
    conn.commit()
    # PRAGMA foreign_keys has no effect inside a transaction → set it before BEGIN.
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("BEGIN")
        try:
            migration(conn)
            violations = conn.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise RuntimeError(
                    f"Migration v{version} violates foreign keys: {[tuple(v) for v in violations[:5]]}"
                )
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
