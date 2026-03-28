from fastapi import Request
from app.engines.document_engine import DocumentProcessingEngine
from app.services.nl2sql.service import NL2SQLService  # Tambahkan import ini

def get_document_engine(request: Request) -> DocumentProcessingEngine:
    return request.app.state.document_engine

def get_nl2sql_service(request: Request) -> NL2SQLService:
    """Mengambil instance NL2SQL dari global state yang sudah dipanaskan."""
    return request.app.state.nl2sql_service