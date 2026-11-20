"""Rate limit per user per kelompok endpoint (DESIGN_GROUP_D.md D9).

Jendela geser (sliding window): setiap kunci menyimpan waktu request dalam
``window`` detik terakhir. Melewati batas → ``RateLimited`` (429 + ``Retry-After``).

Disimpan di memori proses: cukup karena aplikasi berjalan dengan 1 worker.
Penghitung hilang saat restart; bila nanti lebih dari 1 instance, pindahkan ke Redis.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from collections import deque
from collections.abc import Callable

from fastapi import Depends, Request

from app.core.config import app_config
from app.core.errors import RateLimited

logger = logging.getLogger(__name__)

_CLEANUP_EVERY = 1000  # hit; kunci yang sudah tidak aktif dibuang agar memori tidak tumbuh


class RateLimiter:
    def __init__(
        self,
        limits: dict[str, int],
        window_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limits = dict(limits)
        self._window = window_seconds
        self._clock = clock
        self._hits: dict[tuple[str, str], deque[float]] = {}
        self._lock = threading.Lock()
        self._since_cleanup = 0

    def check(self, group: str, key: str) -> None:
        """Catat satu request; lempar ``RateLimited`` bila batas grup terlewati."""
        retry_after = self.hit(group, key)
        if retry_after is not None:
            logger.warning("Rate limit '%s' terlewati (kunci %s), coba lagi %s dtk.",
                           group, key, retry_after)
            raise RateLimited(
                f"Terlalu banyak permintaan. Coba lagi dalam {retry_after} detik.",
                retry_after=retry_after,
            )

    def hit(self, group: str, key: str) -> int | None:
        """None bila diizinkan (dan dicatat); selain itu detik sampai boleh lagi."""
        limit = self._limits[group]
        now = self._clock()
        with self._lock:
            bucket = self._hits.setdefault((group, key), deque())
            while bucket and bucket[0] <= now - self._window:
                bucket.popleft()
            if len(bucket) >= limit:
                return max(1, math.ceil(bucket[0] + self._window - now))
            bucket.append(now)
            self._since_cleanup += 1
            if self._since_cleanup >= _CLEANUP_EVERY:
                self._cleanup(now)
        return None

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
            self._since_cleanup = 0

    def tracked_keys(self) -> int:
        return len(self._hits)

    def _cleanup(self, now: float) -> None:
        stale = [k for k, b in self._hits.items() if not b or b[-1] <= now - self._window]
        for k in stale:
            del self._hits[k]
        self._since_cleanup = 0


limiter = RateLimiter(
    {
        "chat": app_config.RATE_LIMIT_CHAT,
        "voice": app_config.RATE_LIMIT_VOICE,
        "upload": app_config.RATE_LIMIT_UPLOAD,
        "login": app_config.RATE_LIMIT_LOGIN,
        "default": app_config.RATE_LIMIT_DEFAULT,
    },
    window_seconds=app_config.RATE_LIMIT_WINDOW_SECONDS,
)


def client_ip(request: Request) -> str:
    """IP klien (di belakang proxy: dari X-Forwarded-For bila proxy dipercaya uvicorn)."""
    return request.client.host if request.client else "unknown"


def rate_limit(group: str) -> Callable[..., None]:
    """Dependency FastAPI: batas grup `group` per user yang login."""
    from app.core.dependencies import get_current_user  # hindari import melingkar
    from app.services.user.model import CurrentUser

    def _check(user: CurrentUser = Depends(get_current_user)) -> None:
        limiter.check(group, user.id)

    _check.__name__ = f"rate_limit_{group}"
    return _check
