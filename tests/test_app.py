import os
import threading
import uuid

import psycopg
import pytest
import redis
from fastapi.testclient import TestClient

from app.feature_store import FeatureStore
from app.main import TransactionRequest, app


@pytest.fixture(autouse=True)
def clear_test_redis() -> None:
    client = redis.Redis(host="127.0.0.1", port=6379, db=15, decode_responses=True)
    client.flushdb()


def test_health_check() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_score_transaction() -> None:
    payload = {
        "transaction_id": f"txn_{uuid.uuid4().hex[:8]}",
        "idempotency_key": f"key_{uuid.uuid4().hex[:8]}",
        "user_id": "u_1001",
        "amount_minor": 750,
        "currency": "USD",
        "merchant_id": "m_552",
        "merchant_category": "electronics",
        "device_id": "d_77",
        "ip_country": "US",
        "timestamp": "2026-08-08T14:22:31Z",
    }

    with TestClient(app) as client:
        response = client.post("/v1/transactions/score", json=payload)

    assert response.status_code == 200
    assert response.json()["decision"] == "approve"
    assert response.json()["stage"] == "rules"
    assert response.json()["reasons"] == ["trusted_user"]
    assert response.json()["score"] is None
    assert response.json()["latency_ms"] == 18


def test_rules_engine_hard_decline_short_circuits() -> None:
    payload = {
        "transaction_id": f"txn_decline_{uuid.uuid4().hex[:8]}",
        "idempotency_key": f"key_decline_{uuid.uuid4().hex[:8]}",
        "user_id": f"u_{uuid.uuid4().hex[:8]}",
        "amount_minor": 200000,
        "currency": "USD",
        "merchant_id": f"m_{uuid.uuid4().hex[:8]}",
        "merchant_category": "electronics",
        "device_id": f"d_{uuid.uuid4().hex[:8]}",
        "ip_country": "US",
        "timestamp": "2026-08-08T14:22:31Z",
    }

    with TestClient(app) as client:
        response = client.post("/v1/transactions/score", json=payload)

    assert response.status_code == 200
    assert response.json()["decision"] == "decline"
    assert response.json()["stage"] == "rules"
    assert response.json()["reasons"] == ["amount_above_ceiling"]
    assert response.json()["score"] is None


def test_rules_engine_hard_approve_short_circuits() -> None:
    payload = {
        "transaction_id": f"txn_approve_{uuid.uuid4().hex[:8]}",
        "idempotency_key": f"key_approve_{uuid.uuid4().hex[:8]}",
        "user_id": "u_1001",
        "amount_minor": 250,
        "currency": "USD",
        "merchant_id": "m_552",
        "merchant_category": "electronics",
        "device_id": "d_77",
        "ip_country": "US",
        "timestamp": "2026-08-08T14:22:31Z",
    }

    with TestClient(app) as client:
        response = client.post("/v1/transactions/score", json=payload)

    assert response.status_code == 200
    assert response.json()["decision"] == "approve"
    assert response.json()["stage"] == "rules"
    assert response.json()["reasons"] == ["trusted_user"]
    assert response.json()["score"] is None


def test_rules_engine_flag_routes_to_model_stage() -> None:
    payload = {
        "transaction_id": f"txn_flag_{uuid.uuid4().hex[:8]}",
        "idempotency_key": f"key_flag_{uuid.uuid4().hex[:8]}",
        "user_id": f"u_{uuid.uuid4().hex[:8]}",
        "amount_minor": 5000,
        "currency": "USD",
        "merchant_id": f"m_{uuid.uuid4().hex[:8]}",
        "merchant_category": "electronics",
        "device_id": f"d_{uuid.uuid4().hex[:8]}",
        "ip_country": "US",
        "timestamp": "2026-08-08T14:22:31Z",
    }

    with TestClient(app) as client:
        response = client.post("/v1/transactions/score", json=payload)

    assert response.status_code == 200
    assert response.json()["decision"] == "review"
    assert response.json()["stage"] == "model"
    assert response.json()["reasons"] == ["new_merchant_for_user"]
    score = response.json()["score"]
    assert isinstance(score, float)
    assert 0.0 <= score <= 1.0


def test_replays_identical_request_with_same_idempotency_key() -> None:
    payload = {
        "transaction_id": f"txn_{uuid.uuid4().hex[:8]}",
        "idempotency_key": f"key_{uuid.uuid4().hex[:8]}",
        "user_id": "u_1042",
        "amount_minor": 84900,
        "currency": "USD",
        "merchant_id": "m_552",
        "merchant_category": "electronics",
        "device_id": "d_77",
        "ip_country": "US",
        "timestamp": "2026-08-08T14:22:31Z",
    }

    with TestClient(app) as client:
        first = client.post("/v1/transactions/score", json=payload)
        second = client.post("/v1/transactions/score", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()


def test_reused_idempotency_key_with_different_payload_returns_422() -> None:
    payload = {
        "transaction_id": f"txn_{uuid.uuid4().hex[:8]}",
        "idempotency_key": f"key_{uuid.uuid4().hex[:8]}",
        "user_id": "u_1042",
        "amount_minor": 84900,
        "currency": "USD",
        "merchant_id": "m_552",
        "merchant_category": "electronics",
        "device_id": "d_77",
        "ip_country": "US",
        "timestamp": "2026-08-08T14:22:31Z",
    }
    replay_payload = {**payload, "amount_minor": 90000}

    with TestClient(app) as client:
        first = client.post("/v1/transactions/score", json=payload)
        second = client.post("/v1/transactions/score", json=replay_payload)

    assert first.status_code == 200
    assert second.status_code == 422


def test_concurrent_requests_with_same_key_create_one_decision() -> None:
    payload = {
        "transaction_id": f"txn_concurrency_{uuid.uuid4().hex[:8]}",
        "idempotency_key": f"key_concurrency_{uuid.uuid4().hex[:8]}",
        "user_id": "u_1042",
        "amount_minor": 84900,
        "currency": "USD",
        "merchant_id": "m_552",
        "merchant_category": "electronics",
        "device_id": "d_77",
        "ip_country": "US",
        "timestamp": "2026-08-08T14:22:31Z",
    }

    with TestClient(app) as client:
        store = client.app.state.store
        responses: list[dict[str, object]] = []
        errors: list[BaseException] = []
        barrier = threading.Barrier(20)

        def fire_request() -> None:
            try:
                barrier.wait()
                req = TransactionRequest(**payload)
                responses.append(store.score_transaction(req).model_dump())
            except BaseException as exc:  # pragma: no cover - exercised by the regression
                errors.append(exc)

        threads = [threading.Thread(target=fire_request) for _ in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    assert not errors
    assert len(responses) == 20
    assert len({response["decision_id"] for response in responses}) == 1
    assert all(response == responses[0] for response in responses)

    database_url = os.environ.get("DATABASE_URL", "postgresql://darshanpatel@localhost:5432/fraud")
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM decisions WHERE transaction_id = %s",
                (payload["transaction_id"],),
            )
            decision_count = cur.fetchone()[0]
            cur.execute(
                "SELECT COUNT(*) FROM idempotency_keys WHERE key = %s",
                (payload["idempotency_key"],),
            )
            idempotency_count = cur.fetchone()[0]

    assert decision_count == 1
    assert idempotency_count == 1


def test_score_transaction_persists_feature_values_from_redis() -> None:
    previous_db = os.environ.get("REDIS_DB")
    os.environ["REDIS_DB"] = "15"
    try:
        redis.Redis(host="127.0.0.1", port=6379, db=15, decode_responses=True).flushdb()

        payload = {
            "transaction_id": f"txn_feature_{uuid.uuid4().hex[:8]}",
            "idempotency_key": f"key_feature_{uuid.uuid4().hex[:8]}",
            "user_id": "u_1042",
            "amount_minor": 84900,
            "currency": "USD",
            "merchant_id": "m_552",
            "merchant_category": "electronics",
            "device_id": "d_77",
            "ip_country": "US",
            "timestamp": "2026-08-08T14:22:31Z",
        }

        with TestClient(app) as client:
            response = client.post("/v1/transactions/score", json=payload)

        assert response.status_code == 200

        database_url = os.environ.get("DATABASE_URL", "postgresql://darshanpatel@localhost:5432/fraud")
        with psycopg.connect(database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT features FROM decisions WHERE transaction_id = %s",
                    (payload["transaction_id"],),
                )
                row = cur.fetchone()

        assert row is not None
        features = row[0]
        assert features["velocity_1h"] == 1
        assert features["velocity_24h"] == 1
        assert features["merchant_new"] is True
        assert features["device_new"] is True
        assert features["country_new"] is True
        assert "amount_zscore" in features
    finally:
        if previous_db is None:
            os.environ.pop("REDIS_DB", None)
        else:
            os.environ["REDIS_DB"] = previous_db


def test_redis_feature_store_tracks_velocity_deviation_and_novelty() -> None:
    client = redis.Redis(host="127.0.0.1", port=6379, db=15, decode_responses=True)
    client.flushdb()
    store = FeatureStore(client=redis.Redis(host="127.0.0.1", port=6379, db=15, decode_responses=True))

    first = store.compute_features(
        user_id="u_1042",
        transaction_id="txn_1",
        amount_minor=1000,
        merchant_id="m_001",
        device_id="d_001",
        ip_country="US",
        timestamp=1_700_000_000,
    )
    second = store.compute_features(
        user_id="u_1042",
        transaction_id="txn_2",
        amount_minor=2000,
        merchant_id="m_001",
        device_id="d_001",
        ip_country="US",
        timestamp=1_700_000_100,
    )

    assert first["velocity_1h"] == 1
    assert first["velocity_24h"] == 1
    assert first["merchant_new"] is True
    assert first["device_new"] is True
    assert first["country_new"] is True
    assert second["velocity_1h"] == 2
    assert second["velocity_24h"] == 2
    assert second["merchant_new"] is False
    assert second["device_new"] is False
    assert second["country_new"] is False
    assert second["amount_zscore"] == 1.0


