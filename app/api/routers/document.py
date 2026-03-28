import os
import shutil
import logging
from pathlib import Path
from typing import List

from fastapi import APIRouter, File, UploadFile, Form, Depends, HTTPException
from app.api.dependencies import get_document_engine
from app.engines.document_engine import DocumentProcessingEngine

router = APIRouter()
logger = logging.getLogger(__name__)

UPLOAD_DIR = Path("temp_uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/upload", summary="Upload Dokumen Kompetitor untuk Diekstrak")
async def upload_documents(
        files: List[UploadFile] = File(),
        engine: DocumentProcessingEngine = Depends(get_document_engine)
):
    """
    Endpoint untuk menerima file dokumen kompetitor.
    Sistem akan:
    1. Menyimpan file sementara
    2. Ingestion & Indexing ke ChromaDB
    3. Ekstraksi Agentic ke SQLite
    """
    file_paths = []

    try:
        for file in files:
            if not file.filename.lower().endswith(('.pdf', '.md')):
                raise HTTPException(status_code=400,
                                    detail=f"File {file.filename} tidak didukung. Harap gunakan PDF atau Markdown.")

            file_path = UPLOAD_DIR / file.filename
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            file_paths.append(str(file_path))

        result = await engine.process_multiple_files(
            file_paths=file_paths
        )
        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Terjadi kesalahan saat pemrosesan AI: {str(e)}")

    finally:
        # 3. Bersihkan Jejak (Hapus file sementara agar server tidak penuh)
        for path in file_paths:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception as cleanup_error:
                logger.warning(f"Gagal menghapus file sementara {path}: {str(cleanup_error)}")