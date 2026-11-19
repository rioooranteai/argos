"""Isolasi NL2SQL: SQL buatan LLM hanya bisa membaca baris sumber yang dicentang.

Menggantikan test executor lama (mode=ro). Termasuk kasus yang ditemukan saat
spike langkah 7.0: `COUNT(*)` pada tabel lain lolos dari authorizer TEMP VIEW.
"""
from __future__ import annotations

import pytest

from app.core.database import Database
from app.core.migrations import run_migrations
from app.services.nl2sql.executor import SQLExecutionTimeout, execute_scoped_sql


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "t.db"
    db = Database(db_path=path)
    with db.get_connection() as conn:
        run_migrations(conn)
        conn.execute("INSERT INTO users (id, email) VALUES ('u1', 'rahasia@corp.com')")
        conn.execute("INSERT INTO library_documents (id, display_name, owner_id) VALUES ('d1','A','u1')")
        for i, (vid, product, price) in enumerate(
            [("v1", "Avanza", 230.0), ("v2", "Brio", 180.0), ("v3", "Rahasia", 999.0)]
        ):
            conn.execute(
                """INSERT INTO document_versions (id, document_id, version_no, content_hash,
                   original_filename, file_ext, size_bytes, uploaded_by, pipeline_version, stage)
                   VALUES (?, 'd1', ?, ?, 'a.pdf', '.pdf', 1, 'u1', 'p', 'ready')""",
                (vid, i + 1, f"h{i}"),
            )
            conn.execute(
                """INSERT INTO features (document_id, version_id, section_hash, page_number,
                   brand_name, product_name, price) VALUES ('d1', ?, 's', 2, 'X', ?, ?)""",
                (vid, product, price),
            )
    return path


def run(sql, db_path, versions=("v1", "v2"), timeout=5, max_rows=100):
    return execute_scoped_sql(sql, db_path, list(versions), timeout, max_rows)


def test_only_selected_versions_visible(db_path):
    rows, truncated = run("SELECT product_name, version_id, page_number FROM features ORDER BY 1", db_path)
    assert [r["product_name"] for r in rows] == ["Avanza", "Brio"]
    assert rows[0]["version_id"] == "v1" and rows[0]["page_number"] == 2
    assert truncated is False


def test_aggregates_cover_selected_only(db_path):
    rows, _ = run("SELECT COUNT(*) AS n, MAX(price) AS hi FROM features", db_path)
    assert rows == [{"n": 2, "hi": 230.0}]


def test_main_prefix_still_scoped(db_path):
    rows, _ = run("SELECT product_name FROM main.features", db_path)
    assert {r["product_name"] for r in rows} == {"Avanza", "Brio"}


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT COUNT(*) FROM users",             # lolos pada pendekatan TEMP VIEW
        "SELECT email FROM users",
        "SELECT * FROM document_versions",
        "SELECT name FROM sqlite_master",
        "SELECT * FROM conversations",
    ],
)
def test_other_tables_unreachable(db_path, sql):
    with pytest.raises(ValueError):
        run(sql, db_path)


def test_writes_rejected(db_path):
    with pytest.raises(ValueError):
        run("DELETE FROM features", db_path)
    # data asli tidak tersentuh
    rows, _ = run("SELECT COUNT(*) AS n FROM features", db_path, versions=("v1", "v2", "v3"))
    assert rows[0]["n"] == 3


def test_attach_and_pragma_rejected(db_path):
    with pytest.raises(ValueError):
        run(f"ATTACH DATABASE '{db_path.as_posix()}' AS x", db_path)
    with pytest.raises(ValueError):
        run("PRAGMA table_info(features)", db_path)


def test_no_versions_means_no_rows(db_path):
    rows, _ = run("SELECT * FROM features", db_path, versions=())
    assert rows == []


def test_row_cap(db_path):
    rows, truncated = run("SELECT product_name FROM features", db_path, max_rows=1)
    assert len(rows) == 1 and truncated is True


def test_timeout(db_path):
    slow = (
        "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) "
        "SELECT COUNT(*) FROM c"
    )
    with pytest.raises(SQLExecutionTimeout):
        run(slow, db_path, timeout=0.2)
