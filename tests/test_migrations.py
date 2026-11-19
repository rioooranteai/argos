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
              "vision_cache", "extraction_cache"):
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
