import re
import sqlparse
from sqlparse.sql import Statement
from sqlparse.tokens import Keyword, DDL

FORBIDDEN_NL_PATTERNS = [
    r"\b(hapus|drop|delete|truncate|format)\b",
    r"\b(ignore|abaikan).*(instruksi|perintah|system)\b",
    r"(you are now|sekarang kamu adalah|ignore previous|abaikan sebelumnya)",
    r"\b(insert|update|alter|grant|revoke)\b",
]

def sanitize_nl_input(user_input: str) -> str:
    """Mencegah pengguna menyisipkan perintah manipulasi lewat bahasa natural."""
    for pattern in FORBIDDEN_NL_PATTERNS:
        if re.search(pattern, user_input, re.IGNORECASE):
            raise ValueError("Input ditolak: Terdeteksi pola bahasa yang mencurigakan atau tidak diizinkan.")
    return user_input.strip()

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