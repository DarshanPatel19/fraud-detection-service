from __future__ import annotations

import os
import threading
from datetime import datetime, timezone

import pytest
from psycopg_pool import ConnectionPool

from app.models import TransactionRequest
from app.store import PostgresStore

RUN_INTEGRATION = bool(os.environ.get("RUN_INTEGRATION"))


@pytest.mark.skipif(not RUN_INTEGRATION, reason="Integration tests disabled")
def test_idempotency_concurrent() -> None:
    db_url = os.environ["DATABASE_URL"]
    pool = ConnectionPool(conninfo=db_url)
    store = PostgresStore(pool)

    req = TransactionRequest(
        transaction_id="txn_concurrent",
        idempotency_key="idem-key-123",
        user_id="u_1",
        amount_minor=1000,
        currency="USD",
        merchant_id="m_1",
        merchant_category="electronics",
        device_id="d_1",
        ip_country="US",
        timestamp=datetime.now(timezone.utc),
    )

    responses = []

    def worker() -> None:
        try:
            res = store.score_transaction(req)
            responses.append(res)
        except Exception as exc:  # pragma: no cover - integration path
            responses.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(responses) == 20
    # all responses should be equivalent in their dict form
    first = responses[0].model_dump() if hasattr(responses[0], "model_dump") else responses[0]
    for r in responses:
        assert (r.model_dump() if hasattr(r, "model_dump") else r) == first

    # verify exactly one decision row exists for the transaction
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM decisions WHERE transaction_id = %s", (req.transaction_id,))
            cnt = cur.fetchone()[0]
    assert cnt == 1
