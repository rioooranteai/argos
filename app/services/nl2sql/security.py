"""Validasi SQL hasil LLM.

Tidak ada filter kata kunci pada pertanyaan user (DESIGN_GROUP_C.md §5): filter
itu menolak pertanyaan sah ("harga setelah update?"). Keamanan dijaga oleh
validator di bawah, koneksi read-only, TEMP VIEW + authorizer, dan timeout.
"""
import sqlparse
from sqlparse.sql import Statement
from sqlparse.tokens import Keyword, DDL

ALLOWED_STATEMENT_TYPES = {"SELECT"}
FORBIDDEN_KEYWORDS = {"DROP", "DELETE", "INSERT", "UPDATE", "ALTER", "TRUNCATE", "EXEC", "EXECUTE", "REPLACE"}

def validate_generated_sql(sql: str) -> str:
    """Memastikan SQL yang dihasilkan murni hanya SELECT dan tidak mengandung perintah destruktif."""
    parsed = sqlparse.parse(sql.strip())
    if not parsed:
        raise ValueError("LLM menghasilkan struktur SQL yang tidak valid.")

    statement: Statement = parsed[0]

    stmt_type = statement.get_type()
    if stmt_type not in ALLOWED_STATEMENT_TYPES:
        raise ValueError(f"Sistem keamanan memblokir eksekusi. Tipe query '{stmt_type}' dilarang.")

    for token in statement.flatten():
        if token.ttype in (Keyword, DDL):
            if token.normalized.upper() in FORBIDDEN_KEYWORDS:
                raise ValueError(f"Sistem keamanan memblokir eksekusi. Keyword dilarang: {token.value}")

    return sql