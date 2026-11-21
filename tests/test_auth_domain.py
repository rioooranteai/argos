"""Login policy: only verified Google Workspace accounts of the allowed domain."""
from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from jose import jwt

from app.core.config import Secrets, app_config, secrets
from app.core.database import Database
from app.api.dependencies import get_current_user, require_admin
from app.core.errors import PermissionDenied, register_exception_handlers
from app.core.migrations import run_migrations
from app.core.security import is_admin, verify_google_identity
from app.tools.storage.sqlite.user import SQLiteUserRepository

POLICY = Secrets(_env_file=None, ALLOWED_GOOGLE_DOMAIN="corp.com", ADMIN_EMAIL="Boss@corp.com")


class TestVerifyGoogleIdentity:
    def test_workspace_account_allowed(self):
        verify_google_identity({"email_verified": True, "hd": "corp.com"}, POLICY)

    def test_domain_case_insensitive(self):
        verify_google_identity({"email_verified": True, "hd": "CORP.com"}, POLICY)

    def test_personal_gmail_rejected(self):
        # Personal Gmail accounts have no `hd` claim.
        with pytest.raises(PermissionDenied) as e:
            verify_google_identity({"email_verified": True, "email": "x@gmail.com"}, POLICY)
        assert e.value.code == "DOMAIN_NOT_ALLOWED"

    def test_other_workspace_rejected(self):
        with pytest.raises(PermissionDenied):
            verify_google_identity({"email_verified": True, "hd": "other.com"}, POLICY)

    def test_email_suffix_alone_not_enough(self):
        with pytest.raises(PermissionDenied):
            verify_google_identity({"email_verified": True, "email": "x@corp.com"}, POLICY)

    def test_unverified_email_rejected(self):
        with pytest.raises(PermissionDenied) as e:
            verify_google_identity({"email_verified": False, "hd": "corp.com"}, POLICY)
        assert e.value.code == "EMAIL_NOT_VERIFIED"


GMAIL = Secrets(_env_file=None, ALLOWED_GOOGLE_DOMAIN="gmail.com")


class TestGmailMode:
    def test_gmail_account_allowed(self):
        verify_google_identity({"email_verified": True, "email": "Rio.Labs@Gmail.com"}, GMAIL)

    def test_workspace_account_rejected(self):
        with pytest.raises(PermissionDenied) as e:
            verify_google_identity(
                {"email_verified": True, "email": "x@corp.com", "hd": "corp.com"}, GMAIL
            )
        assert e.value.code == "DOMAIN_NOT_ALLOWED"

    def test_non_gmail_address_rejected(self):
        with pytest.raises(PermissionDenied):
            verify_google_identity({"email_verified": True, "email": "x@yahoo.com"}, GMAIL)

    def test_lookalike_domain_rejected(self):
        with pytest.raises(PermissionDenied):
            verify_google_identity({"email_verified": True, "email": "x@evilgmail.com"}, GMAIL)

    def test_unverified_gmail_rejected(self):
        with pytest.raises(PermissionDenied) as e:
            verify_google_identity({"email_verified": False, "email": "x@gmail.com"}, GMAIL)
        assert e.value.code == "EMAIL_NOT_VERIFIED"


def test_is_admin():
    assert is_admin("boss@CORP.com", POLICY)
    assert not is_admin("staff@corp.com", POLICY)
    assert not is_admin("", Secrets(_env_file=None))


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(secrets, "SECRET_KEY", "test-secret")
    monkeypatch.setattr(secrets, "ADMIN_EMAIL", "boss@corp.com")
    database = Database(db_path=tmp_path / "t.db")
    with database.get_connection() as conn:
        run_migrations(conn)
    repo = SQLiteUserRepository(database)

    app = FastAPI()
    register_exception_handlers(app)
    app.state.user_repo = repo

    @app.get("/me")
    def me(user=Depends(get_current_user)):
        return {"id": user.id, "is_admin": user.is_admin}

    @app.get("/admin")
    def admin(user=Depends(require_admin)):
        return {"ok": True}

    return TestClient(app), repo, database


def _token(sub: str) -> str:
    return jwt.encode({"sub": sub, "given_name": "X"}, "test-secret", algorithm=app_config.JWT_ALGORITHM)


def _cookie(token: str) -> dict:
    return {"Cookie": f"{app_config.SESSION_COOKIE_NAME}={token}"}


def test_missing_token_401(client):
    c, _, _ = client
    r = c.get("/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "UNAUTHENTICATED"


def test_valid_user(client):
    c, repo, _ = client
    repo.upsert_on_login("u1", "Staff@corp.com", "Staff", None, new_user_id="u1")
    r = c.get("/me", headers=_cookie(_token("u1")))
    assert r.status_code == 200
    assert r.json() == {"id": "u1", "is_admin": False}


def test_unknown_user_rejected(client):
    c, _, _ = client
    r = c.get("/me", headers=_cookie(_token("ghost")))
    assert r.status_code == 401


def test_inactive_user_rejected(client):
    c, repo, database = client
    repo.upsert_on_login("u1", "staff@corp.com", "Staff", None, new_user_id="u1")
    with database.get_connection() as conn:
        conn.execute("UPDATE users SET is_active = 0 WHERE id = 'u1'")
    r = c.get("/me", headers=_cookie(_token("u1")))
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "USER_INACTIVE"


def test_admin_only(client):
    c, repo, _ = client
    repo.upsert_on_login("u1", "staff@corp.com", "Staff", None, new_user_id="u1")
    repo.upsert_on_login("u2", "boss@corp.com", "Boss", None, new_user_id="u2")
    assert c.get("/admin", headers=_cookie(_token("u1"))).status_code == 403
    assert c.get("/admin", headers=_cookie(_token("u2"))).status_code == 200



def test_login_is_keyed_by_google_sub_and_ids_are_uuid(client):
    import uuid

    _, repo, _ = client
    first = repo.upsert_on_login("google-123", "Staff@corp.com", "Staff", None)
    again = repo.upsert_on_login("google-123", "staff@corp.com", "Staff Baru", "pic")
    assert str(uuid.UUID(first.id)) == first.id          # a UUID, not the Google ID
    assert again.id == first.id and again.name == "Staff Baru"
    other = repo.upsert_on_login("google-456", "lain@corp.com", "Lain", None)
    assert other.id != first.id
