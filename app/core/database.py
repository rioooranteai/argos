import sqlite3
from pathlib import Path
from contextlib import contextmanager

DB_PATH = Path(__file__).resolve().parent.parent.parent / "competitor_data.db"

@contextmanager
def get_connection():
    """
    Context manager untuk koneksi SQLite.
    Otomatis commit jika sukses, rollback jika error, dan selalu close.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    """Membuat tabel SQL jika belum ada saat aplikasi pertama kali berjalan."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS features (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id TEXT NOT NULL,
                competitor_name TEXT NOT NULL,
                feature_name TEXT NOT NULL,
                price REAL,          
                advantages TEXT,             
                disadvantages TEXT              
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_competitor_name
            ON features (competitor_name)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_feature_name
            ON features (feature_name)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_document_id
            ON features (document_id)
        """)


def insert_feature(feature_dict: dict, document_id: str):
    """
    Menyimpan satu baris fitur kompetitor ke tabel SQL.
    feature_dict diharapkan berasal dari CompetitorFeature.model_dump().
    """
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO features (
                document_id,
                competitor_name,
                feature_name,
                price,
                advantages,
                disadvantages
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                document_id,
                feature_dict.get("competitor_name"),
                feature_dict.get("feature_name"),
                feature_dict.get("price"),
                feature_dict.get("advantages"),
                feature_dict.get("disadvantages"),
            ),
        )