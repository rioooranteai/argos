import shutil
import os
from pathlib import Path

# Sesuaikan dengan nama folder tempat ChromaDB menyimpan datanya di proyek Anda.
# Jika Anda mengatur path lain di Config, silakan ubah string di bawah ini.
CHROMA_DIR = "chroma_db"

def clear_chroma_database():
    chroma_path = Path(CHROMA_DIR)
    
    if not chroma_path.exists():
        print(f"INFO: Folder '{CHROMA_DIR}' tidak ditemukan.")
        print("Vector database sudah dalam keadaan bersih atau belum pernah dibuat.")
        return

    try:
        # Menghapus folder chroma_db secara paksa beserta seluruh isinya
        shutil.rmtree(chroma_path)
        print(f"✅ BERHASIL: Folder '{CHROMA_DIR}' dan seluruh data vektor di dalamnya telah dihanguskan!")
        print("Sistem akan otomatis membuat folder database vektor yang baru saat Anda melakukan proses Ingestion berikutnya.")
    except PermissionError:
        print("❌ GAGAL: Terjadi masalah hak akses (Permission Error).")
        print("Penyebab paling umum: Server FastAPI Anda (Uvicorn) masih menyala dan sedang mengunci file database tersebut.")
        print("Solusi: Matikan server Uvicorn sejenak (Ctrl+C), jalankan script ini lagi, lalu nyalakan kembali servernya.")
    except Exception as e:
        print(f"❌ Terjadi kesalahan tidak terduga: {e}")

if __name__ == "__main__":
    print("=== PROSES RESET CHROMA DB ===")
    clear_chroma_database()