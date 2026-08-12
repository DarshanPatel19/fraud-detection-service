from __future__ import annotations

from pathlib import Path

import joblib
from sklearn.linear_model import LogisticRegression

from app.model import ModelArtifact, load_model


def test_load_model_from_artifact_dict(tmp_path: Path) -> None:
    model = LogisticRegression(class_weight="balanced", max_iter=10)
    artifact = {
        "classifier": model,
        "threshold": 0.5,
        "version": "v1.0",
        "feature_order": [
            "velocity_1h",
            "velocity_24h",
            "amount_zscore",
            "merchant_new",
            "device_new",
            "country_new",
        ],
    }
    path = tmp_path / "artifact.joblib"
    joblib.dump(artifact, path)

    loaded = load_model(path)

    assert isinstance(loaded, ModelArtifact)
    assert loaded.version == "v1.0"
    assert loaded.threshold == 0.5
    assert loaded.feature_order[0] == "velocity_1h"
