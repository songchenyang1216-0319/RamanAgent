from __future__ import annotations

from pathlib import Path

from backend.agent.message_normalizer import MessageNormalizer
from backend.agent.planning.json_repair import loads_json_with_repair
from backend.agent.planning.llm_planner import LLMPlanner
from backend.agent.planning.plan_types import LLMPlan
from backend.agent.planning.plan_validator import PlanValidator
from backend.agent.planning.planner_config import PlannerConfig
from backend.agent.planning.tool_catalog import ToolCatalog
from backend.tasks.task_events import format_task_sse


def test_json_repair_handles_markdown_fence_and_trailing_comma() -> None:
    payload, repaired = loads_json_with_repair(
        """```json
        {"plan_type": "tool", "steps": [{"tool_name": "model_tool",}],}
        ```"""
    )
    assert payload["plan_type"] == "tool"
    assert payload["steps"][0]["tool_name"] == "model_tool"
    assert repaired.startswith("{")


def test_planner_config_invalid_env_falls_back_to_hybrid(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PLANNER_MODE", "surprising")
    config = PlannerConfig.from_env()
    assert config.mode == "hybrid"
    assert config.external_allowed is True
    assert config.mock_allowed is True


def test_high_confidence_router_handles_model_status_without_llm() -> None:
    normalized = MessageNormalizer().normalize({"message": "当前大模型是什么", "user_id": "tester"})
    output = LLMPlanner(use_external_model=None, mode="hybrid").plan(normalized, ToolCatalog())
    assert output.plan.plan_type == "tool"
    assert output.plan.steps[0].tool_name == "model_tool"
    assert output.plan.steps[0].action_name == "get_current_model"


def test_validator_requires_confirmation_for_dangerous_action(tmp_path: Path) -> None:
    path = tmp_path / "sample.csv"
    path.write_text("x,y\n1,2\n", encoding="utf-8")
    normalized = MessageNormalizer().normalize({"message": "删除这个文件", "file_path": str(path), "explicit_has_file": True})
    plan = LLMPlan.from_dict(
        {
            "plan_type": "tool",
            "intent": "file_tool.delete",
            "confidence": 1,
            "requires_file": True,
            "requires_confirmation": True,
            "reason": "direct",
            "steps": [{"step_id": "step_001", "tool_name": "file_tool", "action_name": "delete", "args": {}}],
        }
    )
    validation = PlanValidator().validate(plan, normalized)
    assert validation.valid is False
    assert "需要确认" in "；".join(validation.errors)

    plan.steps[0].args["confirmed"] = True
    confirmed = PlanValidator().validate(plan, normalized)
    assert confirmed.valid is True


def test_task_sse_event_format_is_parseable() -> None:
    text = format_task_sse({"event": "task_progress", "task_id": "t1", "content": "ok", "data": {"progress": 50}})
    assert text.startswith("event: task_progress")
    assert '"task_id": "t1"' in text
    assert text.endswith("\n\n")
