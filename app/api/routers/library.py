"""Library: dokumen bersama seluruh karyawan (DESIGN_GROUP_A.md §6, §10)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status

from app.core.dependencies import get_current_user, get_library_service
from app.services.library.model import (
    DocumentDetailOut,
    DocumentOut,
    RenameDocumentRequest,
    UploadBatchOut,
    UploadFileResult,
    VersionOut,
)
from app.services.library.service import LibraryService
from app.services.user.model import CurrentUser

router = APIRouter(prefix="/api/v1/library", tags=["Library"])


@router.post(
    "/documents",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload dokumen baru ke Library (diproses di background)",
)
async def upload_documents(
    files: list[UploadFile] = File(...),
    user: CurrentUser = Depends(get_current_user),
    svc: LibraryService = Depends(get_library_service),
) -> UploadBatchOut:
    """Hasil per file: `queued` (masuk antrean), `existing` (file identik sudah ada,
    dipakai tanpa diproses ulang), atau `rejected` (beserta alasannya)."""
    return UploadBatchOut(results=await svc.upload_documents(user, files))


@router.post(
    "/documents/{document_id}/versions",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload versi baru dari dokumen yang ada",
)
async def upload_new_version(
    document_id: str,
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
    svc: LibraryService = Depends(get_library_service),
) -> UploadFileResult:
    return await svc.upload_new_version(user, document_id, file)


@router.get("/documents", summary="Cari dokumen di Library")
def list_documents(
    q: str | None = Query(default=None, max_length=200),
    uploaded_by: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _: CurrentUser = Depends(get_current_user),
    svc: LibraryService = Depends(get_library_service),
) -> list[DocumentOut]:
    return [DocumentOut.from_item(i) for i in svc.list_documents(q, uploaded_by, limit, offset)]


@router.get("/documents/{document_id}", summary="Detail dokumen beserta riwayat versi")
def get_document(
    document_id: str,
    _: CurrentUser = Depends(get_current_user),
    svc: LibraryService = Depends(get_library_service),
) -> DocumentDetailOut:
    item, versions = svc.get_document(document_id)
    return DocumentDetailOut(
        **DocumentOut.from_item(item).model_dump(),
        versions=[VersionOut.from_version(v) for v in versions],
    )


@router.patch("/documents/{document_id}", summary="Ganti nama tampilan dokumen")
def rename_document(
    document_id: str,
    body: RenameDocumentRequest,
    user: CurrentUser = Depends(get_current_user),
    svc: LibraryService = Depends(get_library_service),
) -> DocumentOut:
    return DocumentOut.from_item(svc.rename_document(user, document_id, body.display_name))


@router.delete(
    "/documents/{document_id}",
    summary="Hapus dokumen (diarsipkan bila masih dipakai notebook orang lain)",
)
def delete_document(
    document_id: str,
    user: CurrentUser = Depends(get_current_user),
    svc: LibraryService = Depends(get_library_service),
) -> dict:
    return {"result": svc.delete_document(user, document_id)}


@router.delete(
    "/documents/{document_id}/versions/{version_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Hapus satu versi dokumen",
)
def delete_version(
    document_id: str,
    version_id: str,
    user: CurrentUser = Depends(get_current_user),
    svc: LibraryService = Depends(get_library_service),
) -> Response:
    svc.delete_version(user, document_id, version_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/versions/{version_id}", summary="Status pemrosesan sebuah versi (untuk polling)")
def get_version_status(
    version_id: str,
    _: CurrentUser = Depends(get_current_user),
    svc: LibraryService = Depends(get_library_service),
) -> VersionOut:
    return VersionOut.from_version(svc.get_version(version_id))
