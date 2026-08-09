from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from app.models import TransactionRequest, TransactionResponse

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
        score DOUBLE PRECISION NOT NULL,
        stage TEXT NOT NULL,
        rule_hits JSONB,
        features JSONB,
        model_version TEXT,
        latency_ms INTEGER NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
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


class SimpleConnectionPool:
    def __init__(self, conninfo: str, size: int = 5) -> None:
        self._conninfo = conninfo
        self._size = size
        self._connections: deque[psycopg.Connection] = deque()
        self._lock = threading.Lock()
        for _ in range(size):
            self._connections.append(psycopg.connect(conninfo))

    def borrow(self) -> psycopg.Connection:
        with self._lock:
            if self._connections:
                return self._connections.popleft()
        return psycopg.connect(self._conninfo)

    def release(self, connection: psycopg.Connection) -> None:
        with self._lock:
            self._connections.append(connection)

    def close(self) -> None:
        with self._lock:
            while self._connections:
                conn = self._connections.popleft()
                conn.close()


class PostgresStore:
    def __init__(self) -> None:
        self._database_url = os.environ.get("DATABASE_URL", "postgresql://darshanpatel@localhost:5432/fraud")
        self._pool = SimpleConnectionPool(self._database_url, size=5)
        self._initialize_schema()

    def _initialize_schema(self) -> None:
        connection = self._pool.borrow()
        try:
            with connection.cursor() as cur:
                for statement in SCHEMA_STATEMENTS:
                    cur.execute(statement)
            connection.commit()
        finally:
            self._pool.release(connection)

    def score_transaction(self, req: TransactionRequest) -> TransactionResponse:
        request_hash = _request_hash(req.model_dump())
        decision_id = f"dec_{uuid.uuid4().hex[:12]}"
        response_body = {
            "decision_id": decision_id,
            "decision": "review",
            "score": 0.62,
            "reasons": ["velocity_1h_exceeded", "new_merchant_for_user"],
            "stage": "model",
            "latency_ms": 18,
        }
        created_at = datetime.now(timezone.utc)

        connection = self._pool.borrow()
        try:
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
                        Jsonb(["velocity_1h_exceeded", "new_merchant_for_user"]),
                        Jsonb({"amount_minor": req.amount_minor, "merchant_category": req.merchant_category}),
                        "v0.1",
                        response_body["latency_ms"],
                        created_at,
                    ),
                )
                connection.commit()
                return TransactionResponse(**response_body)
        except Exception:
            connection.rollback()
            raise
        finally:
            self._pool.release(connection)


def _request_hash(payload: dict[str, Any]) -> str:
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
