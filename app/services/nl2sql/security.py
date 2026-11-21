"""Validation of LLM-generated SQL.

There is no keyword filter on the user's question (DESIGN_GROUP_C.md §5): such a
filter rejected valid questions ("price after the update?"). Safety comes from the
validator below, the isolated in-memory database + authorizer, and the timeout.
"""
import sqlparse
from sqlparse.sql import Statement
from sqlparse.tokens import Keyword, DDL

ALLOWED_STATEMENT_TYPES = {"SELECT"}
FORBIDDEN_KEYWORDS = {"DROP", "DELETE", "INSERT", "UPDATE", "ALTER", "TRUNCATE", "EXEC", "EXECUTE", "REPLACE"}

def validate_generated_sql(sql: str) -> str:
    """Make sure the generated SQL is a pure SELECT with no destructive commands."""
    parsed = sqlparse.parse(sql.strip())
    if not parsed:
        raise ValueError("The LLM produced an invalid SQL structure.")

    statement: Statement = parsed[0]

    stmt_type = statement.get_type()
    if stmt_type not in ALLOWED_STATEMENT_TYPES:
        raise ValueError(f"Blocked by the safety check. Query type '{stmt_type}' is not allowed.")

    for token in statement.flatten():
        if token.ttype in (Keyword, DDL):
            if token.normalized.upper() in FORBIDDEN_KEYWORDS:
                raise ValueError(f"Blocked by the safety check. Forbidden keyword: {token.value}")

    return sql