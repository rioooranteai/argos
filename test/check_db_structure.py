import sqlite3
from pathlib import Path

DB_PATH = "competitor_data.db"

def check_database_structure():
    db_file = Path(DB_PATH)
    
    if not db_file.exists():
        print(f"Gagal: File database '{DB_PATH}' tidak ditemukan.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # 1. Mendapatkan daftar semua tabel di database
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        
        if not tables:
            print("Database ada, tetapi belum memiliki tabel sama sekali.")
            return
            
        print(f"=== STRUKTUR DATABASE: {DB_PATH} ===")
        print(f"Tabel yang ditemukan: {[t[0] for t in tables]}\n")

        # 2. Membedah struktur setiap tabel
        for table in tables:
            table_name = table[0]
            # Abaikan tabel internal SQLite
            if table_name == 'sqlite_sequence':
                continue
                
            print(f"--- Struktur Tabel: '{table_name}' ---")
            
            # PRAGMA table_info mengembalikan info kolom: 
            # (cid, name, type, notnull, dflt_value, pk)
            cursor.execute(f"PRAGMA table_info({table_name});")
            columns = cursor.fetchall()
            
            # Header untuk tabel di terminal
            print(f"{'CID':<5} | {'NAMA KOLOM':<20} | {'TIPE DATA':<15} | {'NOT NULL':<10} | {'PRIMARY KEY'}")
            print("-" * 75)
            
            for col in columns:
                cid = col[0]
                name = col[1]
                data_type = col[2]
                not_null = "Ya" if col[3] else "Tidak"
                is_pk = "Ya" if col[5] else "Tidak"
                
                print(f"{cid:<5} | {name:<20} | {data_type:<15} | {not_null:<10} | {is_pk}")
            
            print("\n")

        # 3. Menampilkan DDL (Data Definition Language) aslinya
        cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='features';")
        ddl_raw = cursor.fetchone()
        if ddl_raw:
            print("--- Query Pembuatan Tabel Asli (DDL) ---")
            print(ddl_raw[0])

    except sqlite3.OperationalError as e:
        print(f"Error saat membaca skema: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    check_database_structure()