"""Health check (DESIGN_GROUP_C.md §6).

- ``/health/live``  — publik; proses hidup. Dipakai healthcheck Docker.
- ``/health/ready`` — khusus admin; status tiap komponen, tanpa memanggil OpenAI.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.core.dependencies import require_admin
from app.services.observability.health import HealthChecker
from app.services.user.model import CurrentUser

router = APIRouter(prefix="/health", tags=["Health Check"])


@router.get("/live", summary="Proses hidup (untuk Docker)")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", summary="Kesiapan tiap komponen (khusus admin)")
def ready(request: Request, _: CurrentUser = Depends(require_admin)) -> JSONResponse:
    checker: HealthChecker = request.app.state.health_checker
    report = checker.ready()
    return JSONResponse(report, status_code=503 if report["status"] == "fail" else 200)
