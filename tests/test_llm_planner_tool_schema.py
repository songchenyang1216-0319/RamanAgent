from __future__ import annotations

from pathlib import Path

import numpy as np

from backend.agent.message_normalizer import MessageNormalizer
from backend.agent.orchestrator import AgentOrchestrator
from backend.agent.planning.llm_planner import LLMPlanner
from backend.agent.planning.plan_types import LLMPlan
from backend.agent.planning.plan_validator import PlanValidator
from backend.agent.planning.tool_catalog import ToolCatalog


def _write_mock_spectrum(path: Path) -> None:
    x = np.linspace(400, 1800, 120)
    y = 0.1 * np.sin(x / 55.0) + np.exp(-0.5 * ((x - 1000) / 40) ** 2) + 0.15
    path.write_text(
        "wavenumber,intensity\n" + "\n".join(f"{float(a)},{float(b)}" for a, b in zip(x, y)),
        encoding="utf-8",
    )


def _normalized(message: str, file_path: str) -> object:
    return MessageNormalizer().normalize(
        {
            "message": message,
            "file_path": file_path,
            "debug": True,
            "explicit_has_file": True,
        }
    )


def test_mock_planner_maps_custom_preprocessing_to_raman_pipeline(tmp_path: Path) -> None:
    path = tmp_path / "spectrum.csv"
    _write_mock_spectrum(path)
    normalized = _normalized("用 SG 平滑 + ALS 去基线 + z-score 归一化处理这个光谱", str(path))
    output = LLMPlanner(use_external_model=False).plan(normalized, ToolCatalog())
    assert output.plan.plan_type == "raman_pipeline"
    assert output.plan.steps[0].tool_name == "raman_pipeline"
    assert output.plan.steps[0].action_name == "run_custom_pipeline"
    assert "savitzky_golay" in output.raw
    validation = PlanValidator().validate(output.plan, normalized)
    assert validation.valid is True


def test_validator_rejects_unknown_tool_with_fallback(tmp_path: Path) -> None:
    path = tmp_path / "spectrum.csv"
    _write_mock_spectrum(path)
    normalized = _normalized("随便规划一个不存在的工具", str(path))
    plan = LLMPlan.from_dict(
        {
            "plan_type": "tool",
            "intent": "bad_tool",
            "confidence": 0.9,
            "requires_file": False,
            "requires_confirmation": False,
            "reason": "mock",
            "steps": [{"step_id": "step_001", "tool_name": "not_a_tool", "action_name": "run", "args": {}}],
        }
    )
    validation = PlanValidator().validate(plan, normalized)
    assert validation.valid is False
    assert validation.should_fallback is True
    assert "tool" in validation.fallback_reason


def test_deep_learning_denoise_reports_missing_model(tmp_path: Path) -> None:
    path = tmp_path / "spectrum.csv"
    _write_mock_spectrum(path)
    normalized = _normalized("用深度学习去噪", str(path))
    output = LLMPlanner(use_external_model=False).plan(normalized, ToolCatalog())
    validation = PlanValidator().validate(output.plan, normalized)
    assert validation.valid is False
    assert validation.should_fallback is False
    assert any("模型文件缺失" in item or "模型" in item for item in validation.errors)


def test_orchestrator_debug_contains_enhanced_planning_fields(tmp_path: Path) -> None:
    path = tmp_path / "spectrum.csv"
    _write_mock_spectrum(path)
    response = AgentOrchestrator().handle_chat(
        {
            "message": "用 SG 平滑 + ALS 去基线 + z-score 归一化处理这个光谱",
            "file_path": str(path),
            "debug": True,
            "explicit_has_file": True,
        }
    )
    assert response["success"] is True
    assert response["route"] == "raman_pipeline"
    assert response["debug"]["rule_intent"]
    assert response["debug"]["llm_plan_raw"]
    assert response["debug"]["validated_plan"]

