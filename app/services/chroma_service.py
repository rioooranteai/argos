import logging
from typing import List

from langchain_chroma import Chroma
from langchain_core.documents import Document

from app.services.shared.base.embedder import BaseEmbedder
from app.services.ingestion.models import Chunk

logger = logging.getLogger(__name__)

class ChromaService:

    def __init__(
        self,
        embedder: BaseEmbedder,
        persist_directory: str = "./chroma_data"
    ):
        self.persist_directory = persist_directory
        self.collection_name = "competitor_intelligence"

        logger.info(f"Inisialisasi Chroma DB di direktori: {persist_directory}")

        self.vector_store = Chroma(
            collection_name=self.collection_name,
            embedding_function=embedder,
            persist_directory=self.persist_directory
        )

    def add_chunks(self, chunks: List[Chunk]) -> List[str]:
        if not chunks:
            logger.warning("Tidak ada chunk untuk dimasukkan ke Chroma DB.")
            return []

        docs = []
        for c in chunks:
            metadata = c.metadata.copy() if c.metadata else {}
            metadata.update({
                "chunk_id": c.chunk_id,
                "source_doc": c.source_doc,
                "competitor_name": c.competitor_name,
                "page_number": c.page_number,
                "content_type": c.content_type.value if hasattr(c.content_type, 'value') else str(c.content_type),
                "section_heading": c.section_heading
            })

            docs.append(Document(page_content=c.text, metadata=metadata, id=c.chunk_id))

        logger.info(f"Menyimpan {len(docs)} dokumen ke Chroma DB...")

        inserted_ids = self.vector_store.add_documents(
            documents=docs,
            ids=[d.id for d in docs]
        )

        return  inserted_ids

    def get_store(self) -> Chroma:
        return self.vector_store