from __future__ import annotations

import time

import pytest

from app.circuit_breaker import CircuitBreaker, CircuitOpenError, ModelTimeoutError


def test_circuit_breaker_opens_after_threshold() -> None:
    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1, max_duration_seconds=0.01)

    def fail() -> None:
        raise ValueError("model error")

    with pytest.raises(ValueError):
        breaker.call(fail)
    with pytest.raises(ValueError):
        breaker.call(fail)
    with pytest.raises(CircuitOpenError):
        breaker.call(fail)


def test_circuit_breaker_half_open_after_timeout() -> None:
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=0.05, max_duration_seconds=0.01)

    def fail() -> None:
        raise ValueError("model error")

    with pytest.raises(ValueError):
        breaker.call(fail)
    with pytest.raises(CircuitOpenError):
        breaker.call(fail)

    time.sleep(0.06)

    def succeed() -> str:
        return "ok"

    assert breaker.call(succeed) == "ok"
    assert breaker.state == "closed"


def test_model_timeout_errors_and_opens_circuit() -> None:
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=0.05, max_duration_seconds=0.001)

    def slow() -> None:
        time.sleep(0.01)

    with pytest.raises(ModelTimeoutError):
        breaker.call(slow)
    with pytest.raises(CircuitOpenError):
        breaker.call(slow)
