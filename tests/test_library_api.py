"""HTTP-level checks for /api/v1/library (auth, status codes, response shape)."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers.library import router
from app.core.config import AppConfig
from app.core.database import Database
from app.core.dependencies import get_current_user, get_library_service
from app.core.errors import register_exception_handlers
from app.core.migrations import run_migrations
from app.infrastructure.providers.repositories.sqlite_library_repository import (
    SQLiteLibraryRepository,
)
from app.infrastructure.providers.repositories.sqlite_user_repository import SQLiteUserRepository
from app.services.library.service import LibraryService
from app.services.user.model import CurrentUser
from tests.library_helpers import make_pdf

ALICE = CurrentUser(id="u1", email="alice@corp.com", name="Alice", given_name="", picture="", is_admin=False)


@pytest.fixture
def client(tmp_path):
    database = Database(db_path=tmp_path / "t.db")
    with database.get_connection() as conn:
        run_migrations(conn)
    SQLiteUserRepository(database).upsert_on_login(ALICE.id, ALICE.email, ALICE.name, None)
    svc = LibraryService(SQLiteLibraryRepository(database), tmp_path / "queue", AppConfig())

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)
    app.dependency_overrides[get_library_service] = lambda: svc
    return app


def test_requires_login(client):
    # get_current_user tidak di-override → tanpa token = 401 dengan format error standar
    r = TestClient(client).get("/api/v1/library/documents")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHENTICATED"


def test_upload_list_detail_status(client):
    client.dependency_overrides[get_current_user] = lambda: ALICE
    c = TestClient(client)

    r = c.post(
        "/api/v1/library/documents",
        files=[("files", ("Pricelist.pdf", make_pdf(2), "application/pdf"))],
    )
    assert r.status_code == 202
    [res] = r.json()["results"]
    assert res["status"] == "queued"

    docs = c.get("/api/v1/library/documents").json()
    assert docs[0]["display_name"] == "Pricelist"
    assert docs[0]["latest_version"]["page_count"] == 2

    detail = c.get(f"/api/v1/library/documents/{res['document_id']}").json()
    assert [v["version_no"] for v in detail["versions"]] == [1]

    status = c.get(f"/api/v1/library/versions/{res['version_id']}").json()
    assert status["stage"] == "queued"

    renamed = c.patch(
        f"/api/v1/library/documents/{res['document_id']}", json={"display_name": "Pricelist Jan"}
    ).json()
    assert renamed["display_name"] == "Pricelist Jan"


def test_unknown_version_404(client):
    client.dependency_overrides[get_current_user] = lambda: ALICE
    r = TestClient(client).get("/api/v1/library/versions/nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"
