from __future__ import annotations

import time


class Stopwatch:
    """Durasi node dalam milidetik untuk trace."""

    def __init__(self) -> None:
        self._start = time.perf_counter()

    def ms(self) -> int:
        return int((time.perf_counter() - self._start) * 1000)
