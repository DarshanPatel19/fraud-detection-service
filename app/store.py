from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from app.circuit_breaker import CircuitBreaker, CircuitOpenError, ModelTimeoutError
from app.feature_store import FeatureStore
from app.model import ModelArtifact
from app.models import TransactionRequest, TransactionResponse
from app.rules import RulesEngine

SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS transactions (
        transaction_id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        amount_minor INTEGER NOT NULL,
        currency TEXT NOT NULL,
        merchant_id TEXT NOT NULL,
        device_id TEXT NOT NULL,
        ip_country TEXT NOT NULL,
        created_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS idempotency_keys (
        key TEXT PRIMARY KEY,
        request_hash TEXT NOT NULL,
        decision_id TEXT,
        response_body JSONB,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS decisions (
        decision_id TEXT PRIMARY KEY,
        transaction_id TEXT NOT NULL,
        decision TEXT NOT NULL,
        score DOUBLE PRECISION,
        stage TEXT NOT NULL,
        rule_hits JSONB,
        features JSONB,
        model_version TEXT,
        latency_ms DOUBLE PRECISION NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
    """
    ALTER TABLE IF EXISTS decisions ALTER COLUMN score DROP NOT NULL
    """,
    """
    ALTER TABLE IF EXISTS decisions ALTER COLUMN latency_ms TYPE DOUBLE PRECISION USING latency_ms
    """,
    """
    CREATE TABLE IF NOT EXISTS failed_events (
        id SERIAL PRIMARY KEY,
        payload JSONB NOT NULL,
        error TEXT,
        attempts INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'pending',
        next_attempt_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """,
]


class StoreConflictError(Exception):
    pass


class PostgresStore:
    def __init__(
        self,
        pool: ConnectionPool,
        feature_store: FeatureStore | None = None,
        model: ModelArtifact | None = None,
        model_breaker: CircuitBreaker | None = None,
    ) -> None:
        self._pool = pool
        self._feature_store = feature_store or FeatureStore()
        self._rules = RulesEngine()
        self._model = model
        self._model_breaker = model_breaker
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        with self._pool.connection() as connection:
            with connection.cursor() as cur:
                for statement in SCHEMA_STATEMENTS:
                    cur.execute(statement)
            connection.commit()

    def score_transaction(self, req: TransactionRequest) -> TransactionResponse:
        start_time = time.perf_counter()
        request_hash = _request_hash(req.model_dump())
        decision_id = f"dec_{uuid.uuid4().hex[:12]}"
        feature_values = self._feature_store.compute_features(
            user_id=req.user_id,
            transaction_id=req.transaction_id,
            amount_minor=req.amount_minor,
            merchant_id=req.merchant_id,
            device_id=req.device_id,
            ip_country=req.ip_country,
            timestamp=int(req.timestamp.timestamp()),
        )
        rule_result = self._rules.evaluate(req.model_dump(), feature_values)
        model_version = None
        score = None
        if rule_result["stage"] == "model":
            if self._model is None or self._model_breaker is None:
                response_body = {
                    "decision_id": decision_id,
                    "decision": rule_result["decision"],
                    "score": None,
                    "reasons": rule_result["reasons"],
                    "stage": "rules_fallback",
                    "latency_ms": 0,
                    "features": feature_values,
                }
            else:
                try:
                    score = self._model_breaker.call(self._model.predict_probability, feature_values)
                    model_version = self._model.version
                    response_body = {
                        "decision_id": decision_id,
                        "decision": "review" if score >= self._model.threshold else "approve",
                        "score": score,
                        "reasons": rule_result["reasons"],
                        "stage": rule_result["stage"],
                        "latency_ms": 0,
                        "features": feature_values,
                    }
                except (CircuitOpenError, ModelTimeoutError):
                    response_body = {
                        "decision_id": decision_id,
                        "decision": rule_result["decision"],
                        "score": None,
                        "reasons": rule_result["reasons"],
                        "stage": "rules_fallback",
                        "latency_ms": 0,
                        "features": feature_values,
                    }
        else:
            response_body = {
                "decision_id": decision_id,
                "decision": rule_result["decision"],
                "score": None,
                "reasons": rule_result["reasons"],
                "stage": rule_result["stage"],
                "latency_ms": 0,
                "features": feature_values,
            }
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        response_body["latency_ms"] = float(elapsed_ms)
        created_at = datetime.now(timezone.utc)

        with self._pool.connection() as connection:
            with connection.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO idempotency_keys (key, request_hash, decision_id, response_body, created_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (key) DO NOTHING
                    RETURNING key
                    """,
                    (
                        req.idempotency_key,
                        request_hash,
                        decision_id,
                        Jsonb(response_body),
                        created_at,
                    ),
                )
                first_seen = cur.fetchone()
                if first_seen is None:
                    cur.execute(
                        """
                        SELECT request_hash, decision_id, response_body
                        FROM idempotency_keys
                        WHERE key = %s
                        """,
                        (req.idempotency_key,),
                    )
                    existing = cur.fetchone()
                    if existing is None:
                        raise StoreConflictError("idempotency key could not be resolved")
                    if existing[0] != request_hash:
                        raise StoreConflictError("idempotency key reused with a different request")
                    connection.commit()
                    return TransactionResponse(**existing[2])

                cur.execute(
                    """
                    INSERT INTO transactions (
                        transaction_id, user_id, amount_minor, currency,
                        merchant_id, device_id, ip_country, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (transaction_id) DO NOTHING
                    """,
                    (
                        req.transaction_id,
                        req.user_id,
                        req.amount_minor,
                        req.currency,
                        req.merchant_id,
                        req.device_id,
                        req.ip_country,
                        created_at,
                    ),
                )
                cur.execute(
                    """
                    INSERT INTO decisions (
                        decision_id, transaction_id, decision, score, stage,
                        rule_hits, features, model_version, latency_ms, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        decision_id,
                        req.transaction_id,
                        response_body["decision"],
                        response_body["score"],
                        response_body["stage"],
                        Jsonb(rule_result["reasons"]),
                        Jsonb(feature_values),
                        model_version,
                        response_body["latency_ms"],
                        created_at,
                    ),
                )
                connection.commit()
                return TransactionResponse(**response_body)


def _request_hash(payload: dict[str, Any]) -> str:
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
