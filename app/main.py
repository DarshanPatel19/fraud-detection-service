from __future__ import annotations

from contextlib import asynccontextmanager
import os
from collections.abc import AsyncIterator

from fastapi import FastAPI, HTTPException
from psycopg_pool import ConnectionPool

from app.model import load_model, ModelArtifact
from app.models import TransactionRequest, TransactionResponse
from app.store import PostgresStore, StoreConflictError


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    database_url = os.environ.get("DATABASE_URL", "postgresql://darshanpatel@localhost:5432/fraud")
    model_path = os.environ.get("MODEL_ARTIFACT_PATH", "model_artifact.joblib")
    pool = ConnectionPool(conninfo=database_url, min_size=1, max_size=5, open=False)
    pool.open()
    app.state.model = load_model(model_path)
    app.state.store = PostgresStore(pool, model=app.state.model)
    try:
        yield
    finally:
        app.state.store = None
        app.state.model = None
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
