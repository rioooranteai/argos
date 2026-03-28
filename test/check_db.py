import sqlite3
from pathlib import Path

DB_PATH = "competitor_data.db"

def view_extracted_data():
    db_file = Path(DB_PATH)
    
    if not db_file.exists():
        print(f"Gagal: File database '{DB_PATH}' tidak ditemukan.")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT * FROM features")
        rows = cursor.fetchall()

        if not rows:
            print("Database ditemukan, tetapi tabel 'features' masih KOSONG.")
            return

        print(f"\n=== MENGAMBIL {len(rows)} BARIS DATA DARI TABEL 'features' ===\n")

        # Membuat header tabel yang dinamis dan pas di layar
        header = f"{'ID':<4} | {'DOC ID':<10} | {'KOMPETITOR':<15} | {'NAMA FITUR':<20} | {'HARGA':<8} | {'KELEBIHAN':<20} | {'KEKURANGAN':<20}"
        print(header)
        print("-" * len(header))

        for row in rows:
            # 1. ID
            r_id = row['id']
            
            # 2. Document ID (Ambil 7 karakter pertama saja agar rapi)
            doc_id = str(row['document_id'])
            doc_id_short = (doc_id[:7] + '...') if len(doc_id) > 10 else doc_id
            
            # 3. Competitor Name
            comp = str(row['competitor_name'])
            comp_short = (comp[:12] + '...') if len(comp) > 15 else comp
            
            # 4. Feature Name
            feat = str(row['feature_name'])
            feat_short = (feat[:17] + '...') if len(feat) > 20 else feat
            
            # 5. Price (Handle NULL/None)
            price_val = row['price']
            price_str = f"${price_val}" if price_val is not None else "NULL"
            
            # 6. Advantages (Handle NULL dan potong teks panjang)
            adv = str(row['advantages']) if row['advantages'] else "NULL"
            adv_short = (adv[:17] + '...') if len(adv) > 20 else adv
            
            # 7. Disadvantages (Handle NULL dan potong teks panjang)
            dis = str(row['disadvantages']) if row['disadvantages'] else "NULL"
            dis_short = (dis[:17] + '...') if len(dis) > 20 else dis

            # Print baris data
            print(f"{r_id:<4} | {doc_id_short:<10} | {comp_short:<15} | {feat_short:<20} | {price_str:<8} | {adv_short:<20} | {dis_short:<20}")

        print("-" * len(header))
        print("Tip: Gunakan UI web Anda untuk melihat data lengkap melalui Asisten NL2SQL.\n")

    except sqlite3.OperationalError as e:
        print(f"Error Database: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    view_extracted_data()