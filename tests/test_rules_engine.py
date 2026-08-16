from __future__ import annotations

from app.rules import RulesEngine


def test_blocked_country_declines() -> None:
    engine = RulesEngine()
    request = {"transaction_id": "t1", "ip_country": "IR", "amount_minor": 100}
    features = {}
    res = engine.evaluate(request, features)
    assert res["decision"] == "decline"
    assert "blocked_country" in res["reasons"]


def test_small_amount_approves() -> None:
    engine = RulesEngine()
    request = {"transaction_id": "t2", "ip_country": "US", "amount_minor": 10}
    features = {}
    res = engine.evaluate(request, features)
    assert res["decision"] == "approve"
    assert "small_amount" in res["reasons"]


def test_velocity_flag() -> None:
    engine = RulesEngine()
    request = {"transaction_id": "t3", "ip_country": "US", "amount_minor": 5000}
    features = {"velocity_1h": 6}
    res = engine.evaluate(request, features)
    assert res["stage"] == "model"
    assert "velocity_1h_exceeded" in res["reasons"]
