import logging
from pathlib import Path
from typing import List, Dict, Any
import chromadb

from app.services.shared.base.embedder import BaseEmbedder


logger = logging.getLogger(__name__)


class ChromaService:
    def __init__(self, embedder: BaseEmbedder, collection_name: str = "competitor_knowledge"):
        self.embedder = embedder
        self.collection_name = collection_name

        self.db_path = Path(__file__).resolve().parent.parent.parent / "chroma_db"
        self.db_path.mkdir(exist_ok=True)

        self.client = chromadb.PersistentClient(path=str(self.db_path))

        self.collection = self.client.get_or_create_collection(name=self.collection_name)

    def add_chunks(self, chunks: list) -> list[str]:
        """
        Menyimpan atau memperbarui chunk ke dalam ChromaDB.
        Dilengkapi dengan filter duplikat, sanitasi metadata, dan mitigasi exception handling.
        """
        if not chunks:
            return []

        ids = []
        documents = []
        metadatas = []
        seen_ids = set()

        for chunk in chunks:
            if chunk.chunk_id in seen_ids:
                logger.debug(f"Mengabaikan chunk duplikat: {chunk.chunk_id}")
                continue
                
            seen_ids.add(chunk.chunk_id)

            clean_meta = {}
            if chunk.metadata:
                for k, v in chunk.metadata.items():
                    if v is None:
                        continue

                    if isinstance(v, (str, int, float, bool)):
                        clean_meta[k] = v

                    elif isinstance(v, list) and all(isinstance(i, (str, int, float, bool)) for i in v):
                        clean_meta[k] = v

                    else:
                        clean_meta[k] = str(v)

            ids.append(chunk.chunk_id)    
            documents.append(chunk.text)
            metadatas.append(clean_meta)

        if not ids:
            return []

        try:
            self.collection.upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas
            )

            return ids
            
        except Exception as e:
            error_msg = f"Gagal menyimpan data ke Vector Database: {str(e)}"
            raise ValueError(error_msg)

    def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        """
        Mencari teks yang paling relevan dengan pertanyaan user.
        Mengembalikan dictionary bawaan dari ChromaDB.
        """
        query_embedding = self.embedder.embed_query(query)

        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=limit
        )

        return results

    def delete_by_ids(self, chunk_ids: List[str]) -> None:
        """
        Menghapus chunk spesifik berdasarkan ID-nya.
        """
        if not chunk_ids:
            return

        self.collection.delete(ids=chunk_ids)

    def delete_by_metadata(self, filter_dict: Dict[str, Any]) -> None:
        """
        Menghapus data berdasarkan kriteria metadata tertentu.
        Contoh parameter: {"source": "4x-strategy.pdf"}
        (Akan menghapus semua data yang berasal dari dokumen tersebut).
        """
        self.collection.delete(where=filter_dict)

    def delete_all(self) -> None:
        """
        Menghapus SELURUH data di dalam collection (Reset Database).
        Sangat berguna untuk proses testing atau membersihkan memori.
        """

        self.client.delete_collection(name=self.collection_name)
        self.collection = self.client.get_or_create_collection(name=self.collection_name)