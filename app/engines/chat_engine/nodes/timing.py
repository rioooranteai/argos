from __future__ import annotations

import time


class Stopwatch:
    """Node duration in milliseconds for the trace."""

    def __init__(self) -> None:
        self._start = time.perf_counter()

    def ms(self) -> int:
        return int((time.perf_counter() - self._start) * 1000)
