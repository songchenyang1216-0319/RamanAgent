from __future__ import annotations

from backend.evaluation.agent_eval.dataset_schema import load_agent_eval_dataset
from backend.evaluation.agent_eval.evaluator import AgentEvaluator


def test_agent_eval_reads_fixtures_and_outputs_metrics() -> None:
    dataset = load_agent_eval_dataset("tests/fixtures/agent_eval_cases.json")
    assert dataset.cases
    result = AgentEvaluator().evaluate(dataset)
    assert result["success"] is True
    assert result["total"] == len(dataset.cases)
    assert "intent_accuracy" in result["metrics"]
    assert "error_rate" in result["metrics"]
