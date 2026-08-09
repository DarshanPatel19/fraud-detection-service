from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


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
