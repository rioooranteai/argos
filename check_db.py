# check_db.py
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "competitor_data.db"

def check_db(db_path: Path = DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Ambil semua tabel yang ada
    tables = cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()

    if not tables:
        print("⚠️  Database kosong, tidak ada tabel.")
        conn.close()
        return

    for table in tables:
        table_name = table["name"]
        rows = cursor.execute(f"SELECT * FROM {table_name}").fetchall()
        count = cursor.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]

        print(f"\n{'='*60}")
        print(f"📋 Tabel: {table_name}  ({count} baris)")
        print(f"{'='*60}")

        if not rows:
            print("  (kosong)")
            continue

        # Print header kolom
        columns = rows[0].keys()
        col_widths = {col: max(len(col), max(len(str(row[col])) for row in rows)) for col in columns}
        header = " | ".join(col.ljust(col_widths[col]) for col in columns)
        print(header)
        print("-" * len(header))

        # Print tiap baris
        for row in rows:
            print(" | ".join(str(row[col]).ljust(col_widths[col]) for col in columns))

    conn.close()

if __name__ == "__main__":
    check_db()