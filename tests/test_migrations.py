"""Schema baseline tests: tables exist, constraints that the design relies on hold."""
from __future__ import annotations

import sqlite3

import pytest

from app.core.database import Database
from app.core.migrations import run_migrations


@pytest.fixture
def db(tmp_path):
    database = Database(db_path=tmp_path / "t.db")
    with database.get_connection() as conn:
        run_migrations(conn)
    return database


def _seed_version(conn, *, doc="d1", ver="v1", h="hash1", no=1):
    conn.execute("INSERT OR IGNORE INTO users (id, email) VALUES ('u1', 'u1@corp.com')")
    conn.execute(
        "INSERT OR IGNORE INTO library_documents (id, display_name, owner_id) VALUES (?, 'Doc', 'u1')",
        (doc,),
    )
    conn.execute(
        """INSERT INTO document_versions
           (id, document_id, version_no, content_hash, original_filename, file_ext,
            size_bytes, uploaded_by, pipeline_version)
           VALUES (?, ?, ?, ?, 'a.pdf', '.pdf', 10, 'u1', 'p1')""",
        (ver, doc, no, h),
    )


def test_expected_tables(db):
    with db.get_connection() as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in ("users", "library_documents", "document_versions", "sections", "features",
              "notebooks", "notebook_sources", "conversations", "messages",
              "vision_cache", "extraction_cache", "pending_uploads", "llm_calls"):
        assert t in names


def test_idempotent(db):
    with db.get_connection() as conn:
        run_migrations(conn)  # second run is a no-op


def test_content_hash_unique(db):
    with pytest.raises(sqlite3.IntegrityError):
        with db.get_connection() as conn:
            _seed_version(conn, ver="v1", h="same")
            _seed_version(conn, ver="v2", h="same", no=2)


def test_pinned_version_cannot_be_deleted(db):
    with db.get_connection() as conn:
        _seed_version(conn)
        conn.execute("INSERT INTO notebooks (id, owner_id, title) VALUES ('n1', 'u1', 'NB')")
        conn.execute(
            "INSERT INTO notebook_sources (notebook_id, document_id, version_id) VALUES ('n1','d1','v1')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        with db.get_connection() as conn:
            conn.execute("DELETE FROM document_versions WHERE id = 'v1'")


def test_version_delete_cascades_features(db):
    with db.get_connection() as conn:
        _seed_version(conn)
        conn.execute(
            """INSERT INTO features (document_id, version_id, section_hash, product_name)
               VALUES ('d1', 'v1', 's1', 'X')"""
        )
        conn.execute("DELETE FROM document_versions WHERE id = 'v1'")
        assert conn.execute("SELECT COUNT(*) FROM features").fetchone()[0] == 0


def test_invalid_stage_rejected(db):
    with pytest.raises(sqlite3.IntegrityError):
        with db.get_connection() as conn:
            _seed_version(conn)
            conn.execute("UPDATE document_versions SET stage = 'weird' WHERE id = 'v1'")


def test_v5_message_status_defaults_and_check(db):
    with db.get_connection() as conn:
        conn.execute("INSERT INTO users (id, email) VALUES ('u1', 'u1@corp.com')")
        conn.execute("INSERT INTO conversations (id, user_id, title) VALUES ('c1', 'u1', 't')")
        conn.execute("INSERT INTO messages (conversation_id, role, content) VALUES ('c1', 'user', 'q')")
        row = conn.execute("SELECT status, error_code, trace FROM messages").fetchone()
        assert tuple(row) == ("ok", None, None)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE messages SET status = 'lost'")


def test_v5_llm_calls_status_check(db):
    with db.get_connection() as conn:
        conn.execute(
            "INSERT INTO llm_calls (purpose, model, latency_ms, status) VALUES ('router', 'm', 5, 'ok')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO llm_calls (purpose, model, latency_ms, status) VALUES ('router', 'm', 5, 'meh')"
            )


# ── Migrasi Python ──────────────────────────────────────────────────────────

def _plain_db(tmp_path):
    conn = sqlite3.connect(tmp_path / "py.db")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def test_python_migration_runs_once_in_a_transaction(tmp_path):
    conn = _plain_db(tmp_path)
    calls = []

    def add_table(c):
        calls.append(1)
        c.execute("CREATE TABLE t (id TEXT PRIMARY KEY)")
        c.execute("INSERT INTO t VALUES ('a')")

    run_migrations(conn, [(1, add_table)])
    run_migrations(conn, [(1, add_table)])
    assert calls == [1]
    assert conn.execute("SELECT id FROM t").fetchall() == [("a",)]
    assert conn.execute("PRAGMA foreign_keys").fetchone() == (1,)


def test_python_migration_failure_rolls_back_everything(tmp_path):
    conn = _plain_db(tmp_path)

    def broken(c):
        c.execute("CREATE TABLE t (id TEXT PRIMARY KEY)")
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        run_migrations(conn, [(1, broken)])
    assert conn.execute("SELECT name FROM sqlite_master WHERE name='t'").fetchone() is None
    assert conn.execute("SELECT COUNT(*) FROM schema_version").fetchone() == (0,)
    assert conn.execute("PRAGMA foreign_keys").fetchone() == (1,)


def test_python_migration_rejects_foreign_key_violations(tmp_path):
    conn = _plain_db(tmp_path)
    conn.executescript("""
        CREATE TABLE parent (id TEXT PRIMARY KEY);
        CREATE TABLE child (id TEXT PRIMARY KEY, parent_id TEXT REFERENCES parent(id));
        INSERT INTO parent VALUES ('p');
        INSERT INTO child VALUES ('c', 'p');
    """)

    def orphan(c):
        c.execute("UPDATE child SET parent_id = 'tidak-ada'")

    with pytest.raises(RuntimeError, match="foreign key"):
        run_migrations(conn, [(1, orphan)])
    assert conn.execute("SELECT parent_id FROM child").fetchone() == ("p",)
