"""Shared pytest fixtures."""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is on sys.path for `app` imports
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Rate limit counters (D9) live in process memory: clear them for every test."""
    from app.core.rate_limit import limiter

    limiter.reset()
    yield
    limiter.reset()
