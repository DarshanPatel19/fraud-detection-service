from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
from sklearn.base import ClassifierMixin

FEATURE_ORDER = (
    "velocity_1h",
    "velocity_24h",
    "amount_zscore",
    "merchant_new",
    "device_new",
    "country_new",
)


@dataclass(frozen=True)
class ModelArtifact:
    classifier: ClassifierMixin
    threshold: float
    version: str
    feature_order: tuple[str, ...] = FEATURE_ORDER

    def predict_probability(self, features: dict[str, Any]) -> float:
        vector = [float(features.get(name, 0.0)) for name in self.feature_order]
        probability = self.classifier.predict_proba([vector])[0][1]
        return float(probability)


def load_model(path: str | Path) -> ModelArtifact:
    artifact = joblib.load(Path(path))
    if isinstance(artifact, ModelArtifact):
        return artifact
    if isinstance(artifact, dict):
        return ModelArtifact(**artifact)
    raise TypeError("loaded model artifact must be a ModelArtifact or dict")
