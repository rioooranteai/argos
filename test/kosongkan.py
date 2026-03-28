import sqlite3
from pathlib import Path

DB_PATH = "competitor_data.db"

def clear_extracted_data():
    db_file = Path(DB_PATH)
    
    if not db_file.exists():
        print(f"Batal: File database '{DB_PATH}' tidak ditemukan.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # 1. Menghapus semua data dari tabel features
        cursor.execute("DELETE FROM features")
        
        # 2. Mereset penghitung ID (AUTOINCREMENT) agar kembali ke 1
        cursor.execute("DELETE FROM sqlite_sequence WHERE name='features'")
        
        # Simpan perubahan
        conn.commit()
        
        print("BERHASIL: Tabel 'features' telah dikosongkan.")
        print("Penghitung ID telah di-reset. Data ekstraksi berikutnya akan dimulai dari ID 1.")

    except sqlite3.OperationalError as e:
        print(f"Error Database: {e}")
        print("Pastikan tabel 'features' memang ada di dalam database.")
    finally:
        conn.close()

if __name__ == "__main__":
    clear_extracted_data()