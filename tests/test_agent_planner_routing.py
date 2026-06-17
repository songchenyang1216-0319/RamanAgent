from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import numpy as np

from backend.agent.message_normalizer import MessageNormalizer
from backend.agent.planning.llm_planner import LLMPlanner
from backend.agent.planning.plan_types import LLMPlan
from backend.agent.planning.plan_validator import PlanValidator
from backend.agent.planning.tool_catalog import ToolCatalog


def _normalize(message: str, **payload):
    base = {"message": message, "conversation_id": f"conv_{uuid4().hex}", "debug": True}
    base.update(payload)
    return MessageNormalizer().normalize(base)


def _spectrum(path: Path) -> Path:
    x = np.linspace(400, 1800, 80)
    y = np.sin(x / 100) + 1
    path.write_text("wavenumber,intensity\n" + "\n".join(f"{a},{b}" for a, b in zip(x, y)), encoding="utf-8")
    return path


def test_general_chat_does_not_trigger_raman() -> None:
    normalized = _normalize("你好，今天帮我写一段项目介绍")
    output = LLMPlanner(use_external_model=False).plan(normalized, ToolCatalog())
    assert output.plan.plan_type == "fallback"
    assert all(step.tool_name != "raman_pipeline" for step in output.plan.steps)


def test_document_question_routes_to_rag(tmp_path: Path) -> None:
    doc = tmp_path / "manual.md"
    doc.write_text("RamanAgent 支持 mixed RAG。", encoding="utf-8")
    normalized = _normalize("根据这个文档说明 mixed RAG 是什么", file_path=str(doc), explicit_has_file=True)
    output = LLMPlanner(use_external_model=False).plan(normalized, ToolCatalog())
    assert output.plan.plan_type == "rag"
    assert output.plan.steps[0].tool_name == "rag"
    assert output.plan.steps[0].action_name == "answer"


def test_raman_csv_preprocessing_routes_to_pipeline(tmp_path: Path) -> None:
    path = _spectrum(tmp_path / "spectrum.csv")
    normalized = _normalize("上传 Raman CSV 后先做 SG 平滑预处理", file_path=str(path), explicit_has_file=True)
    output = LLMPlanner(use_external_model=False).plan(normalized, ToolCatalog())
    assert output.plan.plan_type == "raman_pipeline"
    assert output.plan.steps[0].tool_name == "raman_pipeline"


def test_table_statistics_routes_to_table_tool(tmp_path: Path) -> None:
    table = tmp_path / "orders.csv"
    table.write_text("city,sales\n上海,10\n北京,20\n", encoding="utf-8")
    normalized = _normalize("这个表格 sales 总和是多少？", file_path=str(table), explicit_has_file=True)
    output = LLMPlanner(use_external_model=False).plan(normalized, ToolCatalog())
    assert output.plan.intent == "table_question_answering"
    assert output.plan.steps[0].tool_name == "table_tool"


def test_unknown_request_falls_back_to_normal_model_reply() -> None:
    normalized = _normalize("帮我想三个变量名")
    output = LLMPlanner(use_external_model=False).plan(normalized, ToolCatalog())
    assert output.plan.plan_type == "fallback"


def test_validator_blocks_fabricated_tool() -> None:
    normalized = _normalize("调用一个不存在的工具")
    plan = LLMPlan.from_dict(
        {
            "plan_type": "tool",
            "intent": "bad",
            "confidence": 0.9,
            "requires_file": False,
            "requires_confirmation": False,
            "reason": "bad",
            "steps": [{"tool_name": "made_up_tool", "action_name": "run", "args": {}}],
        }
    )
    validation = PlanValidator().validate(plan, normalized)
    assert validation.valid is False
    assert validation.should_fallback is True


def test_validator_reports_missing_file_for_file_plan() -> None:
    normalized = _normalize("分析这个文件")
    plan = LLMPlan.from_dict(
        {
            "plan_type": "tool",
            "intent": "table_question_answering",
            "confidence": 0.8,
            "requires_file": True,
            "requires_confirmation": False,
            "reason": "needs file",
            "steps": [{"tool_name": "table_tool", "action_name": "analyze_table", "args": {"query": "统计"}}],
        }
    )
    validation = PlanValidator().validate(plan, normalized)
    assert validation.valid is False
    assert "请先上传文件" in "；".join(validation.errors)

