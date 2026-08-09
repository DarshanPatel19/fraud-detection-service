from __future__ import annotations

from datetime import datetime
import uuid

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Fraud Detection Service")


class TransactionRequest(BaseModel):
    transaction_id: str
    idempotency_key: str
    user_id: str
    amount_minor: int
    currency: str
    merchant_id: str
    merchant_category: str
    device_id: str
    ip_country: str
    timestamp: datetime


class TransactionResponse(BaseModel):
    decision_id: str
    decision: str
    score: float
    reasons: list[str]
    stage: str
    latency_ms: int


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/transactions/score", response_model=TransactionResponse)
def score_transaction(req: TransactionRequest) -> TransactionResponse:
    return TransactionResponse(
        decision_id=f"dec_{uuid.uuid4().hex[:12]}",
        decision="review",
        score=0.62,
        reasons=["velocity_1h_exceeded", "new_merchant_for_user"],
        stage="model",
        latency_ms=18,
    )
