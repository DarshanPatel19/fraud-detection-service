from __future__ import annotations

from fastapi import FastAPI, HTTPException

from app.models import TransactionRequest, TransactionResponse
from app.store import PostgresStore, StoreConflictError

app = FastAPI(title="Fraud Detection Service")
store = PostgresStore()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/transactions/score", response_model=TransactionResponse)
def score_transaction(req: TransactionRequest) -> TransactionResponse:
    try:
        return store.score_transaction(req)
    except StoreConflictError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
