"""API tidak bisa dibuka lewat URL di browser (DESIGN_GROUP_D.md D2)."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.errors import register_exception_handlers
from app.core.fetch_metadata import FetchMetadataMiddleware
from app.core.request_context import RequestIDMiddleware

COOKIE = "argos_session"

# Header yang dikirim browser untuk tiap cara membuka URL.
ADDRESS_BAR = {"sec-fetch-mode": "navigate", "sec-fetch-dest": "document", "sec-fetch-site": "none"}
LINK_FROM_APP = {"sec-fetch-mode": "navigate", "sec-fetch-dest": "document", "sec-fetch-site": "same-origin"}
IFRAME = {"sec-fetch-mode": "navigate", "sec-fetch-dest": "iframe", "sec-fetch-site": "same-origin"}
OTHER_SITE_FETCH = {"sec-fetch-mode": "cors", "sec-fetch-dest": "empty", "sec-fetch-site": "cross-site"}
APP_FETCH = {"sec-fetch-mode": "cors", "sec-fetch-dest": "empty", "sec-fetch-site": "same-origin"}


@pytest.fixture
def client():
    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(FetchMetadataMiddleware, allowed_origins=["https://argos.corp.com"],
                       cookie_name=COOKIE)
    app.add_middleware(RequestIDMiddleware)

    @app.get("/api/v1/notebooks")
    def notebooks():
        return {"data": "rahasia"}

    @app.post("/api/v1/notebooks")
    def create():
        return {"ok": True}

    @app.get("/api/v1/auth/google/login")
    def google_login():
        return {"redirect": True}

    @app.get("/health/ready")
    def ready():
        return {"status": "ok"}

    @app.get("/health/live")
    def live():
        return {"status": "ok"}

    @app.get("/docs-like")
    def page():
        return {"page": True}

    return TestClient(app)


@pytest.mark.parametrize("headers", [ADDRESS_BAR, LINK_FROM_APP, IFRAME, OTHER_SITE_FETCH],
                         ids=["address-bar", "link", "iframe", "other-site"])
@pytest.mark.parametrize("path", ["/api/v1/notebooks", "/health/ready"])
def test_browser_navigation_and_other_sites_get_empty_404(client, headers, path):
    r = client.get(path, headers=headers)
    assert r.status_code == 404 and r.content == b""
    assert "rahasia" not in r.text
    assert r.headers.get("x-request-id")  # tetap bisa dilacak di log


def test_same_site_subdomain_is_blocked_too(client):
    r = client.get("/api/v1/notebooks", headers={**APP_FETCH, "sec-fetch-site": "same-site"})
    assert r.status_code == 404


def test_fetch_from_the_app_passes(client):
    assert client.get("/api/v1/notebooks", headers=APP_FETCH).json() == {"data": "rahasia"}


def test_no_fetch_metadata_passes_to_auth(client):
    """curl/skrip: tidak diblokir di sini; login tetap wajib di endpoint."""
    assert client.get("/api/v1/notebooks").status_code == 200


def test_google_login_flow_is_a_navigation_and_allowed(client):
    assert client.get("/api/v1/auth/google/login", headers=ADDRESS_BAR).status_code == 200


def test_unprotected_paths_untouched(client):
    assert client.get("/health/live", headers=ADDRESS_BAR).status_code == 200
    assert client.get("/docs-like", headers=ADDRESS_BAR).status_code == 200


def test_cookie_post_without_fetch_metadata_needs_matching_origin(client):
    client.cookies.set(COOKIE, "x")
    r = client.post("/api/v1/notebooks", headers={"origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "ORIGIN_NOT_ALLOWED"
    assert client.post("/api/v1/notebooks").status_code == 403  # tanpa Origin
    assert client.post("/api/v1/notebooks", headers={"origin": "https://argos.corp.com"}).status_code == 200
    assert client.post("/api/v1/notebooks", headers={"origin": "http://testserver"}).status_code == 200


def test_post_without_cookie_is_not_origin_checked(client):
    # Tanpa cookie tidak ada risiko CSRF; login dicek di lapisan berikutnya.
    r = client.post("/api/v1/notebooks")
    assert r.status_code == 200


def test_cookie_post_from_app_fetch_passes(client):
    client.cookies.set(COOKIE, "x")
    assert client.post("/api/v1/notebooks", headers=APP_FETCH).status_code == 200
