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
    db_uri = f"file:{DB_PATH.as_posix()}?mode=ro"

    conn = sqlite3.connect(db_uri, uri=True)
    conn.row_factory = sqlite3.Row

    try:
        cursor = conn.cursor()
        cursor.execute(sql_query)
        rows = cursor.fetchall()

        result = [dict(row) for row in rows]
        return result
    except sqlite3.Error as e:
        raise ValueError(f"Query gagal dieksekusi oleh database: {str(e)}")
    finally:
        conn.close()