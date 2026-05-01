"""Tests for the read-only SQL executor.

Uses a temp SQLite DB to verify that SQLite's URI mode=ro actually rejects
writes at the driver level — defense in depth even if the validator misses.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE features (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            brand_name TEXT,
            product_name TEXT,
            price REAL
        )
    """)
    conn.execute(
        "INSERT INTO features (brand_name, product_name, price) "
        "VALUES ('Scopely', 'MONOPOLY GO!', 0.0)"
    )
    conn.execute(
        "INSERT INTO features (brand_name, product_name, price) "
        "VALUES ('King', 'Candy Crush', 0.99)"
    )
    conn.commit()
    conn.close()
    return db_path


class TestExecuteReadonly:
    def test_select_returns_rows(self, temp_db):
        from app.services.nl2sql.executor import execute_readonly_sql
        rows = execute_readonly_sql(
            "SELECT brand_name, price FROM features ORDER BY price",
            db_path=temp_db,
        )

        assert len(rows) == 2
        assert rows[0]["brand_name"] == "Scopely"
        assert rows[1]["brand_name"] == "King"
        assert rows[1]["price"] == 0.99

    def test_write_rejected_at_driver_level(self, temp_db):
        from app.services.nl2sql.executor import execute_readonly_sql
        with pytest.raises(ValueError, match="Query gagal"):
            execute_readonly_sql(
                "INSERT INTO features (brand_name) VALUES ('evil')",
                db_path=temp_db,
            )

    def test_drop_rejected_at_driver_level(self, temp_db):
        from app.services.nl2sql.executor import execute_readonly_sql
        with pytest.raises(ValueError):
            execute_readonly_sql("DROP TABLE features", db_path=temp_db)

    def test_invalid_sql_raises_value_error(self, temp_db):
        from app.services.nl2sql.executor import execute_readonly_sql
        with pytest.raises(ValueError):
            execute_readonly_sql(
                "SELECT * FROM nonexistent_table", db_path=temp_db
            )
