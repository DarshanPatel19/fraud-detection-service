from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.circuit_breaker import CircuitBreaker
from app.main import app
from app.model import load_model


def test_model_load_missing_returns_none(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    missing_path = tmp_path / "missing_model.joblib"
    monkeypatch.setenv("MODEL_ARTIFACT_PATH", str(missing_path))
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/fraud")

    with pytest.raises(FileNotFoundError):
        load_model(missing_path)

    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=0.01, max_duration_seconds=0.01)
    breaker.open()
    assert breaker.state == "open"
