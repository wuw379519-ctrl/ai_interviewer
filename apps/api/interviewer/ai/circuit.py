"""In-process circuit breaker (not shared across workers — see D71)."""
from __future__ import annotations

import time
from collections.abc import Callable


class CircuitBreaker:
    def __init__(
        self,
        *,
        failure_threshold: int = 3,
        cooldown_sec: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        self.failure_threshold = failure_threshold
        self.cooldown_sec = cooldown_sec
        self._clock = clock
        self.failures = 0
        self.opened_at: float | None = None
        self.calls_blocked = 0

    def allow(self) -> bool:
        if self.opened_at is None:
            return True
        if self._clock() - self.opened_at >= self.cooldown_sec:
            # Half-open: allow one probe.
            self.opened_at = None
            self.failures = 0
            return True
        self.calls_blocked += 1
        return False

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.failure_threshold:
            self.opened_at = self._clock()

    @property
    def is_open(self) -> bool:
        return self.opened_at is not None and self._clock() - self.opened_at < self.cooldown_sec
