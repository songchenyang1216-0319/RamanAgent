from __future__ import annotations

from backend.agent.message_normalizer import MessageNormalizer
from backend.agent.planning.llm_planner import LLMPlanner
from backend.agent.planning.tool_catalog import ToolCatalog


def test_planner_native_tool_calling_mode_keeps_json_fallback(monkeypatch) -> None:
    monkeypatch.setenv("TOOL_CALLING_MODE", "native")
    planner = LLMPlanner(use_external_model=False, mode="mock")
    normalized = MessageNormalizer().normalize({"message": "查看当前模型", "debug": True})
    prompt = planner._build_prompt(normalized, ToolCatalog())
    assert "TOOL_CALLING_MODE=native" in prompt
    assert "OpenAI-compatible tools schema" in prompt
    output = planner.plan(normalized, ToolCatalog())
    assert output.plan.plan_type in {"fallback", "tool", "model", "rag", "raman_pipeline", "hybrid"}
