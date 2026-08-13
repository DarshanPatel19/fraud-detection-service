from __future__ import annotations

from contextlib import asynccontextmanager
import logging
import os
from collections.abc import AsyncIterator

from fastapi import FastAPI, HTTPException
from psycopg_pool import ConnectionPool

from app.circuit_breaker import CircuitBreaker
from app.model import load_model
from app.models import TransactionRequest, TransactionResponse
from app.store import PostgresStore, StoreConflictError

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    database_url = os.environ.get("DATABASE_URL", "postgresql://darshanpatel@localhost:5432/fraud")
    model_path = os.environ.get("MODEL_ARTIFACT_PATH", "model_artifact.joblib")
    failure_threshold = int(os.environ.get("MODEL_BREAKER_FAILURE_THRESHOLD", "3"))
    recovery_timeout = float(os.environ.get("MODEL_BREAKER_RECOVERY_TIMEOUT", "10.0"))
    max_duration_ms = float(os.environ.get("MODEL_BREAKER_MAX_DURATION_MS", "20"))
    pool = ConnectionPool(conninfo=database_url, min_size=1, max_size=5, open=False)
    pool.open()
    app.state.model_breaker = CircuitBreaker(
        failure_threshold=failure_threshold,
        recovery_timeout=recovery_timeout,
        max_duration_seconds=max_duration_ms / 1000.0,
    )
    try:
        app.state.model = load_model(model_path)
    except FileNotFoundError as exc:
        logger.warning("model artifact not found at %s, starting in rules-only mode", model_path)
        app.state.model = None
        app.state.model_breaker.open()
    app.state.store = PostgresStore(pool, model=app.state.model, model_breaker=app.state.model_breaker)
    try:
        yield
    finally:
        app.state.store = None
        app.state.model = None
        app.state.model_breaker = None
        pool.close()


app = FastAPI(title="Fraud Detection Service", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/transactions/score", response_model=TransactionResponse)
def score_transaction(req: TransactionRequest) -> TransactionResponse:
    store = app.state.store
    if store is None:
        raise RuntimeError("store is not initialized")
    try:
        return store.score_transaction(req)
    except StoreConflictError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
