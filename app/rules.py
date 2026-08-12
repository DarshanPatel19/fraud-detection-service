from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


class RulesEngine:
    def __init__(self, config_path: str | Path | None = None) -> None:
        config_file = Path(config_path) if config_path is not None else Path(__file__).with_name("rules.json")
        self._rules = self._load(config_file)

    @staticmethod
    def _load(config_path: str | Path) -> list[dict[str, Any]]:
        with Path(config_path).open("r", encoding="utf-8") as handle:
            rules = json.load(handle)
        if not isinstance(rules, list):
            raise ValueError("rules config must be a list")
        return rules

    def evaluate(self, request: Mapping[str, Any], features: Mapping[str, Any]) -> dict[str, Any]:
        payload = dict(request)
        payload.update(features)

        for rule in self._rules:
            if self._matches(rule.get("when"), payload):
                outcome = rule.get("outcome", "flag")
                reason = rule.get("reason")
                if outcome == "hard_decline":
                    return {"decision": "decline", "reasons": [reason], "stage": "rules"}
                if outcome == "hard_approve":
                    return {"decision": "approve", "reasons": [reason], "stage": "rules"}
                return {"decision": "review", "reasons": [reason], "stage": "model"}

        return {"decision": "review", "reasons": [], "stage": "model"}

    def _matches(self, condition: Any, payload: Mapping[str, Any]) -> bool:
        if condition is None:
            return True
        if isinstance(condition, dict):
            if "all" in condition:
                return all(self._matches(item, payload) for item in condition["all"])
            if "any" in condition:
                return any(self._matches(item, payload) for item in condition["any"])
            if "field" in condition:
                return self._evaluate_condition(condition, payload)
            return False
        return bool(condition)

    def _evaluate_condition(self, condition: Mapping[str, Any], payload: Mapping[str, Any]) -> bool:
        field = condition["field"]
        actual = payload.get(field)
        op = condition.get("op", "eq")
        expected = condition.get("value")

        if op == "eq":
            return actual == expected
        if op == "ne":
            return actual != expected
        if op == "in":
            return actual in expected if isinstance(expected, (list, tuple, set)) else False
        if op == "not_in":
            return actual not in expected if isinstance(expected, (list, tuple, set)) else True
        if op == "gt":
            return actual is not None and actual > expected
        if op == "gte":
            return actual is not None and actual >= expected
        if op == "lt":
            return actual is not None and actual < expected
        if op == "lte":
            return actual is not None and actual <= expected
        return False
