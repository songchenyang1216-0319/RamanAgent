from __future__ import annotations

from typing import Any


METRIC_NAMES = [
    "intent_accuracy",
    "route_accuracy",
    "tool_selection_accuracy",
    "algorithm_selection_accuracy",
    "fallback_rate",
    "repair_rate",
    "clarification_rate",
    "error_rate",
]


def _mean(values: list[bool]) -> float:
    if not values:
        return 0.0
    return sum(1 for value in values if value) / len(values)


def compute_agent_eval_metrics(rows: list[dict[str, Any]]) -> dict[str, float]:
    return {
        "intent_accuracy": _mean([row["intent_match"] for row in rows if row.get("expected_intent")]),
        "route_accuracy": _mean([row["route_match"] for row in rows if row.get("expected_route")]),
        "tool_selection_accuracy": _mean([row["tool_match"] for row in rows if row.get("expected_tool")]),
        "algorithm_selection_accuracy": _mean([row["algorithm_match"] for row in rows if row.get("expected_algorithm")]),
        "fallback_rate": _mean([row.get("fallback", False) for row in rows]),
        "repair_rate": _mean([row.get("repair", False) for row in rows]),
        "clarification_rate": _mean([row.get("clarification", False) for row in rows]),
        "error_rate": _mean([row.get("error", False) for row in rows]),
    }
