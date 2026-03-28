import sqlite3
import logging
from pathlib import Path
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).resolve().parent.parent.parent.parent / "competitor_data.db"


def execute_readonly_sql(sql_query: str) -> List[Dict[str, Any]]:
    """
    Mengeksekusi SQL dengan mode STRICT READ-ONLY.
    Jika ada perintah selain SELECT, database engine akan menolak di level driver.
    """
    # Menggunakan URI string dengan ?mode=ro untuk keamanan absolut
    db_uri = f"file:{DB_PATH.as_posix()}?mode=ro"

    logger.info(f"Mengeksekusi SQL (Read-Only Mode): {sql_query}")

    # Harus menggunakan uri=True agar mode=ro terbaca
    conn = sqlite3.connect(db_uri, uri=True)
    conn.row_factory = sqlite3.Row

    try:
        cursor = conn.cursor()
        cursor.execute(sql_query)
        rows = cursor.fetchall()

        # Konversi hasil ke dictionary
        result = [dict(row) for row in rows]
        return result
    except sqlite3.Error as e:
        logger.error(f"Kesalahan Database SQLite: {e}")
        raise ValueError(f"Query gagal dieksekusi oleh database: {str(e)}")
    finally:
        conn.close()