import logging
from pathlib import Path
from pydantic_ai import Agent

from app.core.config import Config
from app.services.extraction.models import CompetitorFeature
from app.core.database import insert_feature
from app.services.chroma_service import ChromaService

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parent.parent.parent.parent / "prompts" / "extraction_agent.md"

def _load_prompt(path: Path) -> str:
    try:
        content = path.read_text(encoding="utf-8")
        # LOGGER PENTING: Memastikan prompt eksternal berhasil terbaca
        logger.info(f"✅ SUKSES memuat System Prompt eksternal dari: {path}")
        logger.debug(f"Isi Prompt (50 chars pertama): {content[:50]}...")
        return content
    except FileNotFoundError:
        # LOGGER PENTING: Peringatan keras jika file tidak ditemukan
        logger.warning(f"⚠️ GAGAL menemukan file prompt di: {path}")
        logger.warning("⚠️ Menggunakan SYSTEM PROMPT DEFAULT (Hardcoded) sebagai fallback.")
        return (
            "Kamu adalah AI Data Extraction Specialist. "
            "Tugasmu: Mengekstrak Nama Kompetitor, Nama Fitur, Harga, dan Kelebihan/Kekurangan "
            "dari KESELURUHAN dokumen yang diberikan. "
            "Lakukan cross-referensi jika informasi tersebar. "
            "Jika tidak ada, kembalikan null. DILARANG MENGARANG."
        )

_SYSTEM_PROMPT = _load_prompt(_PROMPT_PATH)

extraction_agent = Agent(
    model=f"openai:{Config.OPENAI_LLM_MODEL}", 
    output_type=list[CompetitorFeature],
    system_prompt=_SYSTEM_PROMPT,
)

_MAX_CHUNK_CHARS = 100000 
_MIN_CHUNK_CHARS = 80

class ExtractionService:
    """
    Service untuk mengekstrak data kompetitor dari dokumen
    yang sudah di-index di Vector DB (ChromaDB) secara KESELURUHAN (Full-Document).
    """

    async def process_indexed_document(
            self,
            document_id: str,
            chroma_svc: ChromaService,
    ) -> dict:
        logger.info(f"Mulai ekstraksi agentic (Full-Document Mode) untuk document_id='{document_id}'")

        chroma_data = chroma_svc.collection.get(
            where={"document_id": document_id},
            include=["documents", "metadatas"],
        )

        chunks_text: list[str] = chroma_data.get("documents", [])
        
        if not chunks_text:
            logger.warning(f"Tidak ada chunk di ChromaDB untuk document_id='{document_id}'")
            return {"status": "failed", "total_features_extracted": 0}

        # 1. FILTER NOISE & GABUNGKAN SEMUA TEKS SEKALIGUS
        valid_texts = [text for text in chunks_text if len(text.strip()) >= _MIN_CHUNK_CHARS]
        
        if not valid_texts:
            logger.warning("Semua chunk terlalu pendek (noise filter aktif). Ekstraksi dibatalkan.")
            return {"status": "failed", "total_features_extracted": 0}

        # Menggabungkan semua chunk menjadi satu kesatuan dokumen utuh
        combined_text = "\n\n--- Bagian Lanjutan ---\n\n".join(valid_texts)
        
        logger.info(f"Dokumen utuh berhasil dirakit dari {len(valid_texts)} chunks valid.")
        logger.info(f"Total panjang teks yang akan diumpankan ke LLM: {len(combined_text)} karakter.")

        # 2. PEMOTONGAN TEKS JIKA MELEBIHI CONTEXT WINDOW (Opsional)
        if len(combined_text) > _MAX_CHUNK_CHARS:
            logger.warning(f"Dokumen terlalu panjang ({len(combined_text)} chars), memotong ke {_MAX_CHUNK_CHARS} karakter untuk mencegah token overflow.")
            combined_text = combined_text[:_MAX_CHUNK_CHARS]

        total_saved = 0

        # 3. PANGGIL AGEN EKSTRAKSI SEKALI SAJA
        logger.info("Memanggil LLM untuk menganalisis keseluruhan dokumen. Mohon tunggu...")
        try:
            result = await extraction_agent.run(combined_text)
            extracted_features: list[CompetitorFeature] = result.output

            if not extracted_features:
                logger.info("Agen tidak menemukan data fitur yang relevan di dokumen ini.")
            else:
                for feature in extracted_features:
                    # Validasi dasar
                    if not feature.competitor_name or not feature.feature_name:
                        logger.debug(f"Skip feature dengan nama/kompetitor kosong: {feature}")
                        continue

                    # Simpan ke SQLite
                    insert_feature(feature.model_dump(), document_id)
                    total_saved += 1

                logger.info(f"BERHASIL! Tersimpan {total_saved} fitur ke database SQL.")

        except Exception as e:
            logger.error(f"Gagal saat proses ekstraksi Full-Document: {e}", exc_info=True)

        return {
            "status": "success",
            "document_id": document_id,
            "total_features_extracted": total_saved,
        }