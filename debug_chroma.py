# reset_chroma.py
import chromadb

client = chromadb.PersistentClient(path="./chroma_db")  # ← sesuaikan path

for col in client.list_collections():
    client.delete_collection(col.name)
    print(f"Deleted: {col.name}")

print("Semua collection dihapus. Silakan upload ulang dokumen.")