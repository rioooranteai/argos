"""Library: documents shared by every employee."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status

from app.api.dependencies import get_current_user, get_library_service, rate_limit
from app.api.schemas.library import (
    DocumentDetailOut,
    DocumentOut,
    RenameDocumentRequest,
    ResolvePendingRequest,
    UploadBatchOut,
    VersionOut,
)
from app.services.library.model import UploadFileResult
from app.services.library.service import LibraryService
from app.services.user.model import CurrentUser

router = APIRouter(prefix="/api/v1/library", tags=["Library"])


@router.post(
    "/documents",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload new documents to the Library (processed in the background)",
    dependencies=[Depends(rate_limit("upload"))],
)
async def upload_documents(
    files: list[UploadFile] = File(...),
    user: CurrentUser = Depends(get_current_user),
    svc: LibraryService = Depends(get_library_service),
) -> UploadBatchOut:
    """Result per file: `queued` (added to the queue), `existing` (an identical file
    already exists and is reused without reprocessing), `similar` (resembles a Library
    document; waiting for a choice via `POST /pending/{pending_id}/resolve`), or `rejected`."""
    return UploadBatchOut(results=await svc.upload_documents(user, files))


@router.post(
    "/pending/{pending_id}/resolve",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Similar upload: make it a new version of the similar document, or a separate document",
    dependencies=[Depends(rate_limit("upload"))],
)
async def resolve_pending(
    pending_id: str,
    body: ResolvePendingRequest,
    user: CurrentUser = Depends(get_current_user),
    svc: LibraryService = Depends(get_library_service),
) -> UploadFileResult:
    return await svc.resolve_pending(user, pending_id, body.action)


@router.post(
    "/documents/{document_id}/versions",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a new version of an existing document",
    dependencies=[Depends(rate_limit("upload"))],
)
async def upload_new_version(
    document_id: str,
    file: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
    svc: LibraryService = Depends(get_library_service),
) -> UploadFileResult:
    return await svc.upload_new_version(user, document_id, file)


@router.get("/documents", summary="Search Library documents")
def list_documents(
    q: str | None = Query(default=None, max_length=200),
    uploaded_by: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _: CurrentUser = Depends(get_current_user),
    svc: LibraryService = Depends(get_library_service),
) -> list[DocumentOut]:
    return [DocumentOut.from_item(i) for i in svc.list_documents(q, uploaded_by, limit, offset)]


@router.get("/documents/{document_id}", summary="Document details with version history")
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


@router.patch("/documents/{document_id}", summary="Rename a document")
def rename_document(
    document_id: str,
    body: RenameDocumentRequest,
    user: CurrentUser = Depends(get_current_user),
    svc: LibraryService = Depends(get_library_service),
) -> DocumentOut:
    return DocumentOut.from_item(svc.rename_document(user, document_id, body.display_name))


@router.delete(
    "/documents/{document_id}",
    summary="Delete a document (archived if another user's notebook still uses it)",
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
    summary="Delete one document version",
)
def delete_version(
    document_id: str,
    version_id: str,
    user: CurrentUser = Depends(get_current_user),
    svc: LibraryService = Depends(get_library_service),
) -> Response:
    svc.delete_version(user, document_id, version_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/versions/{version_id}", summary="Processing status of a version (for polling)")
def get_version_status(
    version_id: str,
    _: CurrentUser = Depends(get_current_user),
    svc: LibraryService = Depends(get_library_service),
) -> VersionOut:
    return VersionOut.from_version(svc.get_version(version_id))
