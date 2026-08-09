from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_check() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_score_transaction() -> None:
    payload = {
        "transaction_id": "txn_8f2c",
        "idempotency_key": "8f2c-4b1a-...",
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
