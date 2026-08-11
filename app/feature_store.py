from __future__ import annotations

import math
import os
from typing import Any

import redis


class FeatureStore:
    def __init__(self, client: redis.Redis | None = None) -> None:
        self._client = client or redis.Redis(
            host=os.environ.get("REDIS_HOST", "127.0.0.1"),
            port=int(os.environ.get("REDIS_PORT", "6379")),
            db=int(os.environ.get("REDIS_DB", "0")),
            decode_responses=True,
        )

    def compute_features(
        self,
        *,
        user_id: str,
        transaction_id: str,
        amount_minor: int,
        merchant_id: str,
        device_id: str,
        ip_country: str,
        timestamp: int,
    ) -> dict[str, Any]:
        pipe = self._client.pipeline(transaction=True)
        vel_key = f"vel:{user_id}"
        pipe.zadd(vel_key, {transaction_id: timestamp})
        pipe.zremrangebyscore(vel_key, "-inf", timestamp - 3600)
        pipe.zcard(vel_key)
        pipe.expire(vel_key, 86400)

        user_hash = f"dev:{user_id}"
        pipe.hincrbyfloat(user_hash, "count", 1)
        pipe.hincrbyfloat(user_hash, "sum", amount_minor)
        pipe.hincrbyfloat(user_hash, "sum_sq", amount_minor * amount_minor)
        pipe.expire(user_hash, 86400)

        merchant_key = f"novelty:{user_id}:merchant"
        device_key = f"novelty:{user_id}:device"
        country_key = f"novelty:{user_id}:country"
        pipe.sismember(merchant_key, merchant_id)
        pipe.sismember(device_key, device_id)
        pipe.sismember(country_key, ip_country)
        pipe.sadd(merchant_key, merchant_id)
        pipe.sadd(device_key, device_id)
        pipe.sadd(country_key, ip_country)
        pipe.expire(merchant_key, 86400)
        pipe.expire(device_key, 86400)
        pipe.expire(country_key, 86400)

        result = pipe.execute()
        velocity_count = int(result[2])
        count, total, total_sq = (
            float(value) if value is not None else 0.0
            for value in self._client.hmget(user_hash, ["count", "sum", "sum_sq"])
        )
        mean = total / count if count else 0.0
        variance = total_sq / count - mean * mean if count else 0.0
        stddev = math.sqrt(max(variance, 0.0))
        zscore = (amount_minor - mean) / stddev if stddev else 0.0

        return {
            "velocity_1h": velocity_count,
            "velocity_24h": velocity_count,
            "amount_zscore": round(zscore, 6),
            "merchant_new": result[8] == 0,
            "device_new": result[9] == 0,
            "country_new": result[10] == 0,
        }
