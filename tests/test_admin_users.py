"""Tahap 2: admin menonaktifkan user, kepemilikan dokumen dialihkan."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jose import jwt

from app.api.routers.admin import router
from app.core.config import AppConfig, app_config, secrets
from app.core.database import Database
from app.core.dependencies import get_admin_service
from app.core.errors import register_exception_handlers
from app.core.migrations import run_migrations
from app.infrastructure.providers.repositories.sqlite_library_repository import (
    SQLiteLibraryRepository,
)
from app.infrastructure.providers.repositories.sqlite_user_repository import SQLiteUserRepository
from app.services.library.service import LibraryService
from app.services.user.admin import AdminService
from app.services.user.model import CurrentUser
from tests.library_helpers import make_pdf, upload

ALICE = CurrentUser(id="u1", email="alice@corp.com", name="Alice", given_name="", picture="", is_admin=False)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(secrets, "SECRET_KEY", "test-secret")
    monkeypatch.setattr(secrets, "ADMIN_EMAIL", "boss@corp.com")
    db = Database(db_path=tmp_path / "t.db")
    with db.get_connection() as conn:
        run_migrations(conn)
    users = SQLiteUserRepository(db)
    users.upsert_on_login("u1", "alice@corp.com", "Alice", None, new_user_id="u1")
    users.upsert_on_login("u2", "bob@corp.com", "Bob", None, new_user_id="u2")
    users.upsert_on_login("admin", "boss@corp.com", "Boss", None, new_user_id="admin")
    library_repo = SQLiteLibraryRepository(db)
    library = LibraryService(library_repo, tmp_path / "queue", AppConfig(), users=users)
    svc = AdminService(users, library_repo)

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router)
    app.state.user_repo = users
    app.dependency_overrides[get_admin_service] = lambda: svc
    return TestClient(app), library, library_repo, users


def auth(sub: str) -> dict:
    token = jwt.encode({"sub": sub}, "test-secret", algorithm=app_config.JWT_ALGORITHM)
    return {"Authorization": f"Bearer {token}"}


def test_only_admin_can_list(env):
    c, *_ = env
    assert c.get("/api/v1/admin/users", headers=auth("u1")).status_code == 403
    users = c.get("/api/v1/admin/users", headers=auth("admin")).json()
    assert {u["email"] for u in users} == {"alice@corp.com", "bob@corp.com", "boss@corp.com"}
    assert next(u for u in users if u["email"] == "boss@corp.com")["is_admin"] is True


async def test_deactivate_transfers_ownership_and_blocks_access(env):
    c, library, repo, _ = env
    [r] = await library.upload_documents(ALICE, [upload(make_pdf(1), "a.pdf")])

    out = c.patch("/api/v1/admin/users/u1", json={"is_active": False}, headers=auth("admin")).json()
    assert out["is_active"] is False and out["documents_transferred"] == 1
    assert repo.get_document(r.document_id).owner_id == "admin"
    assert repo.get_version(r.version_id).uploaded_by == "u1"  # riwayat pengunggah tetap

    # Token Alice yang masih berlaku langsung ditolak
    r2 = c.get("/api/v1/admin/users", headers=auth("u1"))
    assert r2.status_code == 403 and r2.json()["error"]["code"] == "USER_INACTIVE"


def test_reactivate(env):
    c, *_ = env
    c.patch("/api/v1/admin/users/u2", json={"is_active": False}, headers=auth("admin"))
    out = c.patch("/api/v1/admin/users/u2", json={"is_active": True}, headers=auth("admin")).json()
    assert out["is_active"] is True and out["documents_transferred"] == 0


def test_admin_cannot_deactivate_self(env):
    c, *_ = env
    r = c.patch("/api/v1/admin/users/admin", json={"is_active": False}, headers=auth("admin"))
    assert r.status_code == 400 and r.json()["error"]["code"] == "CANNOT_DEACTIVATE_ADMIN"


def test_unknown_user(env):
    c, *_ = env
    assert c.patch("/api/v1/admin/users/x", json={"is_active": False}, headers=auth("admin")).status_code == 404
