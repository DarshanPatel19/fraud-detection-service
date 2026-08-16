# Real-Time Fraud Detection Service

This repository contains the initial skeleton for the fraud detection service.

## Benchmarks (placeholders)

| Path | p50 | p95 | p99 | Notes |
|---|---:|---:|---:|---|
| rules-only | TBD | TBD | TBD | measured with locust against `POST /v1/transactions/score` when rules short-circuit |
| model path | TBD | TBD | TBD | measured with locust against `POST /v1/transactions/score` when model is invoked |

Run a quick load locally with locust:

```bash
pip install -r requirements.txt
locust -f locustfile.py --host=http://localhost:8000
```

