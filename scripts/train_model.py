from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import auc, precision_recall_curve, precision_score, recall_score
from sklearn.model_selection import train_test_split


@dataclass(frozen=True)
class TransactionSample:
    velocity_1h: int
    velocity_24h: int
    amount_zscore: float
    merchant_new: int
    device_new: int
    country_new: int
    label: int


def generate_samples(n: int, fraud_rate: float = 0.1, random_state: int | None = None) -> list[TransactionSample]:
    rng = np.random.default_rng(random_state)
    samples: list[TransactionSample] = []
    for _ in range(n):
        velocity_1h = rng.integers(0, 10)
        velocity_24h = max(velocity_1h, rng.integers(0, 50))
        amount_zscore = float(rng.normal(0.0, 1.5))
        merchant_new = int(rng.random() < 0.2)
        device_new = int(rng.random() < 0.2)
        country_new = int(rng.random() < 0.15)

        if rng.random() < fraud_rate:
            label = 1
            if rng.random() < 0.7:
                velocity_1h = max(velocity_1h, rng.integers(5, 12))
                velocity_24h = max(velocity_24h, velocity_1h + rng.integers(0, 20))
            if rng.random() < 0.6:
                amount_zscore = max(amount_zscore, rng.normal(4.0, 1.5))
            if rng.random() < 0.65:
                merchant_new = 1
            if rng.random() < 0.6:
                device_new = 1
            if rng.random() < 0.55:
                country_new = 1
        else:
            label = 0
            if merchant_new and rng.random() < 0.6:
                amount_zscore = max(amount_zscore, rng.normal(1.5, 1.0))

        samples.append(
            TransactionSample(
                velocity_1h=int(velocity_1h),
                velocity_24h=int(velocity_24h),
                amount_zscore=round(float(amount_zscore), 6),
                merchant_new=int(merchant_new),
                device_new=int(device_new),
                country_new=int(country_new),
                label=label,
            )
        )
    return samples


def build_feature_matrix(samples: list[TransactionSample]) -> tuple[list[list[float]], list[int]]:
    X = [
        [
            sample.velocity_1h,
            sample.velocity_24h,
            sample.amount_zscore,
            sample.merchant_new,
            sample.device_new,
            sample.country_new,
        ]
        for sample in samples
    ]
    y = [sample.label for sample in samples]
    return X, y


def pick_threshold(y_true: list[int], probs: list[float]) -> tuple[float, float, float, float]:
    precision, recall, thresholds = precision_recall_curve(y_true, probs)
    pr_auc = auc(recall, precision)
    if len(thresholds) == 0:
        return 0.5, 0.0, 0.0, pr_auc

    f1_scores = [2 * p * r / (p + r) if p + r else 0.0 for p, r in zip(precision[:-1], recall[:-1])]
    best_index = int(np.argmax(f1_scores))
    threshold = float(thresholds[best_index])
    best_precision = float(precision[best_index])
    best_recall = float(recall[best_index])
    return threshold, best_precision, best_recall, pr_auc


def main() -> None:
    parser = argparse.ArgumentParser(description="Train a synthetic fraud model")
    parser.add_argument("--samples", type=int, default=25000)
    parser.add_argument("--fraud-rate", type=float, default=0.12)
    parser.add_argument("--output", type=Path, default=Path("model_artifact.joblib"))
    parser.add_argument("--random-state", type=int, default=42)
    args = parser.parse_args()

    samples = generate_samples(args.samples, fraud_rate=args.fraud_rate, random_state=args.random_state)
    X, y = build_feature_matrix(samples)
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.3, random_state=args.random_state, stratify=y
    )

    model = LogisticRegression(class_weight="balanced", max_iter=1000, random_state=args.random_state)
    model.fit(X_train, y_train)

    y_probs = model.predict_proba(X_test)[:, 1].tolist()
    threshold, precision, recall, pr_auc = pick_threshold(y_test, y_probs)
    y_pred = [1 if prob >= threshold else 0 for prob in y_probs]
    test_precision = precision_score(y_test, y_pred)
    test_recall = recall_score(y_test, y_pred)

    artifact = {
        "classifier": model,
        "threshold": threshold,
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
    joblib.dump(artifact, args.output)

    print(json.dumps({
        "samples": len(samples),
        "fraud_rate": args.fraud_rate,
        "precision": precision,
        "recall": recall,
        "pr_auc": pr_auc,
        "threshold": threshold,
        "test_precision": test_precision,
        "test_recall": test_recall,
        "output": str(args.output),
    }, indent=2))


if __name__ == "__main__":
    main()
