from __future__ import annotations

from datetime import datetime, timezone

import fakeredis

from app.feature_store import FeatureStore


def test_compute_features_basic() -> None:
    fake = fakeredis.FakeRedis()
    store = FeatureStore(client=fake)

    ts = int(datetime.now(timezone.utc).timestamp())
    features = store.compute_features(
        user_id="u_test",
        transaction_id="txn1",
        amount_minor=1000,
        merchant_id="m_1",
        device_id="d_1",
        ip_country="US",
        timestamp=ts,
    )

    assert "velocity_1h" in features
    assert "amount_zscore" in features
    assert isinstance(features["amount_zscore"], float)
