from __future__ import annotations

import threading
import time
from typing import Any, Callable


class CircuitOpenError(Exception):
    pass


class ModelTimeoutError(Exception):
    pass


class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout: float = 10.0,
        max_duration_seconds: float = 0.02,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._max_duration_seconds = max_duration_seconds
        self._lock = threading.Lock()
        self._failures = 0
        self._state = "closed"
        self._open_until = 0.0

    @property
    def state(self) -> str:
        with self._lock:
            if self._state == "open" and time.monotonic() >= self._open_until:
                self._state = "half_open"
            return self._state

    def allow_request(self) -> bool:
        with self._lock:
            if self._state == "open":
                if time.monotonic() >= self._open_until:
                    self._state = "half_open"
                    return True
                return False
            return True

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._state = "closed"
            self._open_until = 0.0

    def record_failure(self) -> None:
        with self._lock:
            if self._state == "half_open":
                self._state = "open"
                self._failures = 0
                self._open_until = time.monotonic() + self._recovery_timeout
                return

            self._failures += 1
            if self._failures >= self._failure_threshold:
                self._state = "open"
                self._open_until = time.monotonic() + self._recovery_timeout
                self._failures = 0

    def call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        if not self.allow_request():
            raise CircuitOpenError("circuit breaker is open")

        result: dict[str, Any] = {}

        def runner() -> None:
            try:
                result["value"] = func(*args, **kwargs)
            except Exception as exc:  # pragma: no cover - propagated explicitly
                result["error"] = exc

        thread = threading.Thread(target=runner, daemon=True)
        thread.start()
        thread.join(self._max_duration_seconds)
        if thread.is_alive():
            self.record_failure()
            raise ModelTimeoutError("model inference exceeded time limit")

        if "error" in result:
            self.record_failure()
            raise result["error"]

        self.record_success()
        return result.get("value")
