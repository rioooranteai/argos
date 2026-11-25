"""Health check.

- ``/health/live``  — public; the process is alive. Used by the Docker healthcheck.
- ``/health/ready`` — admin only; the status of each component, without calling OpenAI.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.dependencies import get_health_checker, require_admin
from app.services.health.checker import HealthChecker
from app.services.user.model import CurrentUser

router = APIRouter(prefix="/health", tags=["Health Check"])


@router.get("/live", summary="Process is alive (for Docker)")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", summary="Readiness of each component (admin only)")
def ready(
    _: CurrentUser = Depends(require_admin),
    checker: HealthChecker = Depends(get_health_checker),
) -> JSONResponse:
    report = checker.ready()
    return JSONResponse(report, status_code=503 if report["status"] == "fail" else 200)
