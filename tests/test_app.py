import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import psycopg
from fastapi.testclient import TestClient

from app.main import TransactionRequest, app, store

client = TestClient(app)


def test_health_check() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_score_transaction() -> None:
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

    response = client.post("/v1/transactions/score", json=payload)

    assert response.status_code == 200
    assert response.json()["decision"] == "review"
    assert response.json()["stage"] == "model"
    assert response.json()["latency_ms"] == 18


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

    def call_endpoint() -> dict[str, object]:
        with TestClient(app) as local_client:
            response = local_client.post("/v1/transactions/score", json=payload)
            return response.json()

    with ThreadPoolExecutor(max_workers=20) as executor:
        responses = list(executor.map(lambda _: call_endpoint(), range(20)))

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


def test_concurrent_requests_with_same_key_create_single_decision() -> None:
    transaction_id = f"txn_{uuid.uuid4().hex[:8]}"
    idempotency_key = f"key_{uuid.uuid4().hex[:8]}"
    payload = {
        "transaction_id": transaction_id,
        "idempotency_key": idempotency_key,
        "user_id": "u_1042",
        "amount_minor": 84900,
        "currency": "USD",
        "merchant_id": "m_552",
        "merchant_category": "electronics",
        "device_id": "d_77",
        "ip_country": "US",
        "timestamp": "2026-08-08T14:22:31Z",
    }

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
    assert len({response["score"] for response in responses}) == 1
    assert len({response["stage"] for response in responses}) == 1

    with psycopg.connect(os.environ.get("DATABASE_URL", "postgresql://darshanpatel@localhost:5432/fraud")) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM decisions WHERE transaction_id = %s", (transaction_id,))
            count = cur.fetchone()[0]

    assert count == 1
