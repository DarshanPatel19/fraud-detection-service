from __future__ import annotations

import uuid
import datetime
import random

from locust import HttpUser, between, task


class FraudUser(HttpUser):
    wait_time = between(0.01, 0.02)

    @task(10)
    def randomized_score(self):
        # Randomize across many users/merchants/devices and amounts so requests
        # exercise the model path instead of consistently short-circuiting.
        user_id = f"u_{random.randint(1,5000)}"
        merchant_id = f"m_{random.randint(1,2000)}"
        device_id = f"d_{random.randint(1,5000)}"
        amount_minor = random.randint(100, 200000)  # cents

        payload = {
            "transaction_id": f"txn_{uuid.uuid4().hex[:8]}",
            "idempotency_key": uuid.uuid4().hex,
            "user_id": user_id,
            "amount_minor": amount_minor,
            "currency": "USD",
            "merchant_id": merchant_id,
            "merchant_category": "electronics",
            "device_id": device_id,
            "ip_country": "US",
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
        }
        self.client.post("/v1/transactions/score", json=payload)

    @task(5)
    def fixed_scenario(self):
        # Keep the original fixed scenario as a secondary task to cover the
        # existing rules-only or established-merchant path.
        payload = {
            "transaction_id": f"txn_{uuid.uuid4().hex[:8]}",
            "idempotency_key": uuid.uuid4().hex,
            "user_id": "u_load",
            "amount_minor": 84900,
            "currency": "USD",
            "merchant_id": "m_552",
            "merchant_category": "electronics",
            "device_id": "d_77",
            "ip_country": "US",
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
        }
        self.client.post("/v1/transactions/score", json=payload)
