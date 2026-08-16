# Real-Time Fraud Detection Service

This service scores card transactions for fraud risk at authorization time. Each
incoming transaction is evaluated through a layered pipeline: a configurable
rules engine that can short-circuit straight to an approve or decline, and a
logistic regression model for the cases the rules flag as ambiguous. Request-time
features — transaction velocity, spend deviation from the user's history, and
novelty of merchant, device, and IP country — are computed from a Redis-backed
feature store on every call. Every decision is written to Postgres as an
append-only audit record, and requests are idempotent on a client-supplied key
so retries never produce a second decision for the same transaction.

## Guarantees

- **Idempotent under retries.** The same `idempotency_key` submitted more than
  once returns the original decision instead of creating a new one, as long as
  the request body is unchanged. A retry with the same key but a different body
  is rejected.
- **Sub-50ms decisions.** Feature computation is a single pipelined Redis round
  trip, rules evaluation is in-process, and the model call is wrapped in a
  circuit breaker with a hard wall-clock budget, so no single request can stall
  behind a slow model.
- **Degrades to rules-only when the model fails.** If the model is unavailable,
  times out, or trips the circuit breaker's failure threshold, the service
  falls back to the rules engine's own decision rather than failing the
  request.
- **Every decision is reproducible from the audit trail.** The `decisions`
  table stores the decision, score, pipeline stage, the rules that fired, the
  computed features, the model version, and the latency for every transaction,
  so any past decision can be explained without re-running the pipeline.

## Architecture

```
Client
  |
  |  POST /v1/transactions/score
  v
FastAPI (app/main.py)
  |
  v
PostgresStore.score_transaction (app/store.py)
  |
  |-- 1. Redis feature store (app/feature_store.py)
  |      velocity_1h / velocity_24h, amount_zscore, merchant_new,
  |      device_new, country_new -- one pipelined round trip
  |
  |-- 2. Rules engine (app/rules.py, app/rules.json)
  |      ordered, config-driven checks over the request + features;
  |      hard_decline / hard_approve short-circuit, otherwise the
  |      transaction is flagged for the model
  |
  |-- 3. Model (app/model.py), via circuit breaker (app/circuit_breaker.py)
  |      logistic regression predicts a fraud probability;
  |      skipped entirely if rules already decided, and bypassed
  |      with a rules-only fallback if the circuit breaker is open
  |
  v
Postgres (idempotency_keys, transactions, decisions)
  |
  v
TransactionResponse
```

Request flow in detail:

1. FastAPI validates the request body against the `TransactionRequest` model
   and hands it to `PostgresStore.score_transaction`.
2. The store computes a SHA-256 hash of the normalized request body, used
   later for idempotency comparison.
3. `FeatureStore.compute_features` issues one Redis pipeline that updates a
   per-user sorted set for velocity, a per-user running mean/variance for the
   amount z-score, and per-user sets for merchant/device/country novelty, then
   reads the results back.
4. `RulesEngine.evaluate` walks `app/rules.json` in order against the request
   and computed features. The first matching rule either decides immediately
   (`hard_decline` / `hard_approve`) or flags the transaction for the model. If
   nothing matches, the transaction also goes to the model with no reasons
   attached.
5. If the rules routed to the model and a model is loaded, the store calls
   `ModelArtifact.predict_probability` through the `CircuitBreaker`, which runs
   the call in a background thread with a wall-clock timeout, opens after
   repeated failures, and raises rather than letting a stuck call block the
   request. On any circuit breaker error, or if no model was loaded at
   startup, the store falls back to the rules engine's own decision under
   stage `rules_fallback`.
6. The store atomically claims the idempotency key in Postgres. If the key is
   new, it inserts the transaction and the decision (including the computed
   features and latency) in the same transaction and commits. If the key was
   already used, it either returns the previously stored response (identical
   request) or raises a conflict error (different request), which FastAPI maps
   to a 422.

The model itself is a scikit-learn `LogisticRegression` trained offline by
`scripts/train_model.py` on synthetic data and loaded once at process startup
via `joblib`. A small checkout-style demo UI that exercises the same endpoint
is served at `/demo`.

## Running locally

These steps use Homebrew-installed Postgres and Redis rather than Docker.

```bash
brew install postgresql@16 redis
brew services start postgresql@16
brew services start redis

createdb fraud

# The service's default DATABASE_URL assumes a Postgres role matching the
# original author's OS username. Homebrew's Postgres creates a superuser role
# matching your own OS username instead, so export DATABASE_URL explicitly:
export DATABASE_URL="postgresql://$(whoami)@localhost:5432/fraud"

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Trains a logistic regression model on synthetic data and writes
# model_artifact.joblib to the current directory.
python scripts/train_model.py

uvicorn app.main:app --reload
```

The service reads its configuration from environment variables, all of which
have working local defaults:

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql://darshanpatel@localhost:5432/fraud` | Postgres connection string |
| `REDIS_HOST` | `127.0.0.1` | Redis host |
| `REDIS_PORT` | `6379` | Redis port |
| `REDIS_DB` | `0` | Redis logical database |
| `MODEL_ARTIFACT_PATH` | `model_artifact.joblib` | Path to the trained model artifact |
| `MODEL_BREAKER_FAILURE_THRESHOLD` | `3` | Consecutive model failures before the circuit opens |
| `MODEL_BREAKER_RECOVERY_TIMEOUT` | `10.0` | Seconds the circuit stays open before allowing a retry |
| `MODEL_BREAKER_MAX_DURATION_MS` | `20` | Wall-clock budget for a single model call |

If `model_artifact.joblib` doesn't exist, the service starts in rules-only
mode instead of failing.

Run the test suite with:

```bash
pytest -q
```

One test (`tests/test_idempotency_concurrent.py`) is skipped unless
`RUN_INTEGRATION=true` is set, since it exercises real concurrent writes
against Postgres.

## API contract

### `POST /v1/transactions/score`

Request body:

```json
{
  "transaction_id": "txn_a1b2c3d4",
  "idempotency_key": "a3f9c2e1-...",
  "user_id": "u_1001",
  "amount_minor": 8490,
  "currency": "USD",
  "merchant_id": "m_552",
  "merchant_category": "electronics",
  "device_id": "d_77",
  "ip_country": "US",
  "timestamp": "2026-08-08T14:22:31Z"
}
```

| Field | Type | Notes |
|---|---|---|
| `transaction_id` | string | Caller-assigned identifier for the transaction |
| `idempotency_key` | string | Caller-assigned key; retries with this key and an identical body replay the original decision |
| `user_id` | string | Identifies the customer for velocity and novelty tracking |
| `amount_minor` | integer | Transaction amount in minor currency units (for example, cents) |
| `currency` | string | ISO 4217 currency code |
| `merchant_id` | string | Identifies the merchant for novelty tracking |
| `merchant_category` | string | Merchant category, passed through but not used by the rules or model |
| `device_id` | string | Identifies the device for novelty tracking |
| `ip_country` | string | ISO 3166-1 alpha-2 country code of the request's originating IP |
| `timestamp` | string | RFC 3339 timestamp of the transaction |

Response body (200):

```json
{
  "decision_id": "dec_5ef05a44fec3",
  "decision": "review",
  "score": 0.8122499518939827,
  "reasons": ["new_merchant_for_user"],
  "stage": "model",
  "latency_ms": 6.93,
  "features": {
    "velocity_1h": 1,
    "velocity_24h": 1,
    "amount_zscore": 0.0,
    "merchant_new": true,
    "device_new": true,
    "country_new": true
  }
}
```

| Field | Type | Notes |
|---|---|---|
| `decision_id` | string | Server-assigned identifier for this decision |
| `decision` | string | One of `approve`, `review`, `decline` |
| `score` | float or null | Model fraud probability, `null` when the decision came from rules alone |
| `reasons` | array of strings | Names of the rules that fired; empty if none did |
| `stage` | string | One of `rules`, `model`, `rules_fallback` |
| `latency_ms` | float | Time spent computing features, evaluating rules, and calling the model |
| `features` | object | The computed features used for this decision |

Errors:

- `422 Unprocessable Entity` when `idempotency_key` is reused with a request
  body that doesn't match the original, or the request fails schema
  validation.

## Benchmarks

Measured locally with `locustfile.py` against a single `uvicorn` worker
process on an M-series MacBook Air, 20 concurrent users for 60 seconds, with
Postgres and Redis running on the same machine.

| Metric | Value |
|---|---|
| Throughput | 1,089 req/s |
| p50 latency | 2 ms |
| p95 latency | 6 ms |
| p99 latency | 12 ms |
| Failures | 0 over 60s |

These numbers describe one process on one machine, not a deployed,
horizontally scaled service — see Limitations.

## Design decisions

**`INSERT ... ON CONFLICT` instead of check-then-insert.** Claiming an
idempotency key with a `SELECT` followed by an `INSERT` is a race: two
requests with the same key can both pass the `SELECT` before either commits
its `INSERT`, producing two decisions for one transaction. `INSERT ...
ON CONFLICT (key) DO NOTHING RETURNING key` claims the key atomically in a
single statement — exactly one concurrent request gets a row back, and every
other request reads the winner's stored response instead of racing to write
its own.

**Redis, not Postgres, for velocity counters.** Velocity and novelty features
are read and written on every single scoring request, are only useful for a
short recent window, and don't need to survive a restart. Doing this
bookkeeping as a Postgres query would mean scanning or counting rows in a
hot table on every request and would compete with the durable audit-trail
writes for the same connection pool. Redis's in-memory sorted sets and sets
make this a constant-time, sub-millisecond operation that stays off the
critical path of the durable writes.

**Rules evaluate before the model.** Features are computed once and used by
both the rules and the model, so this isn't about avoiding the Redis round
trip. It's about keeping the model's blast radius small: clear-cut cases —
blocked countries, amounts over the hard ceiling, known-bad devices,
trusted users, trivially small amounts — get a deterministic, auditable
answer from simple, inspectable logic instead of a probabilistic model, and
only the genuinely ambiguous remainder ever reaches the model.

**The circuit breaker falls back to rules-only.** The model is treated as a
best-effort enhancement over a rules baseline, not a dependency the
transaction path can be blocked by. The circuit breaker enforces a wall-clock
budget on each model call and opens after repeated failures so the service
stops paying a timeout on every request during an outage, degrading straight
to the rules engine's own decision instead of failing the request or hanging.

## Limitations

- **The model is trained on synthetic data at a 12% fraud rate.**
  `scripts/train_model.py` generates its own training data with a fraud rate
  far higher than real card-present or card-not-present fraud, which is
  typically well under 1%. The model's precision, recall, and threshold are
  tuned to that synthetic distribution, not to production traffic, and it
  would need retraining on real, correctly labeled data before its scores
  could be trusted for actual decisions.
- **There is no retry queue for failed downstream events.** The schema
  includes a `failed_events` table, but nothing in the codebase currently
  writes to it or drains it; a failure downstream of the decision itself
  (for example, a webhook or export step) is not retried anywhere today.
- **The benchmarks are single-process, local measurements.** They were taken
  with one `uvicorn` worker and both dependencies on the same machine as the
  client generating load. They say nothing about behavior under network
  latency to Postgres or Redis, multiple worker processes, or realistic
  production concurrency.
