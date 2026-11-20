"""Tests for NL2SQL security guards.

This module is the security-critical layer between user input / LLM output
and the database. Bugs here are exploitable, so coverage is non-negotiable.
"""
from __future__ import annotations

import pytest

from app.services.nl2sql import security
from app.services.nl2sql.security import validate_generated_sql


def test_no_keyword_filter_on_user_questions():
    """Filter kata kunci NL dihapus (DESIGN_GROUP_C.md §5)."""
    assert not hasattr(security, "sanitize_nl_input")
    assert not hasattr(security, "FORBIDDEN_NL_PATTERNS")


# ------------------------------ validate_generated_sql -------------------------

class TestValidateGeneratedSQL:
    @pytest.mark.parametrize("safe_sql", [
        "SELECT * FROM features",
        "SELECT brand_name FROM features WHERE price < 100",
        "SELECT brand_name, COUNT(*) FROM features GROUP BY brand_name",
        "select * from features order by price desc limit 10",
    ])
    def test_select_passes(self, safe_sql):
        assert validate_generated_sql(safe_sql) == safe_sql

    @pytest.mark.parametrize("unsafe_sql", [
        "DROP TABLE features",
        "DELETE FROM features",
        "INSERT INTO features VALUES (1, 'a', 'b', 0, 'x', 'y')",
        "UPDATE features SET price = 0",
        "ALTER TABLE features ADD COLUMN evil TEXT",
        "TRUNCATE features",
    ])
    def test_destructive_sql_rejected(self, unsafe_sql):
        with pytest.raises(ValueError, match="Sistem keamanan"):
            validate_generated_sql(unsafe_sql)

    def test_empty_sql_rejected(self):
        with pytest.raises(ValueError):
            validate_generated_sql("")

    def test_garbage_sql_rejected(self):
        with pytest.raises(ValueError):
            validate_generated_sql("this is not sql at all")

    def test_select_with_destructive_in_string_literal(self):
        """
        Edge case: 'DROP' appearing inside a string literal should still be
        recognized by sqlparse as a value, not a keyword. The validator parses
        SQL semantically rather than via raw substring match.
        """
        sql = "SELECT * FROM features WHERE product_name = 'DROP TABLE simulator'"
        # Should pass because DROP is inside a string literal, not a keyword
        result = validate_generated_sql(sql)
        assert result == sql
