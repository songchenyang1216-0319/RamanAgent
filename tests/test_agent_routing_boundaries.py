from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.agent.intent_router import IntentRouter
from backend.agent.message_normalizer import MessageNormalizer
from backend.agent.planner import Planner


def _plan(payload: dict):
    normalized = MessageNormalizer().normalize(payload)
    intent = IntentRouter().route(normalized)
    plan = Planner().make_plan(normalized, intent)
    return normalized, intent, plan


def test_knowledge_question_without_file_routes_to_model():
    _, intent, plan = _plan({"message": "WebSocket 是什么？", "conversation_id": "routing-boundary-chat"})
    assert intent.intent == "general_chat"
    assert plan.route_type == "model"
    assert plan.skill_name is None


def test_file_question_routes_to_conversation_rag():
    _, intent, plan = _plan(
        {
            "message": "根据这个文件回答问题",
            "conversation_id": "routing-boundary-rag",
            "files": [{"file_id": "file_1", "path": "storage/workspaces/u/c/uploads/a.txt"}],
        }
    )
    assert intent.intent == "conversation_rag"
    assert plan.route_type == "rag"
    assert plan.rag_scope == "conversation"


def test_knowledge_base_question_routes_to_kb_rag():
    _, intent, plan = _plan(
        {
            "message": "请查一下知识库里的项目规范",
            "conversation_id": "routing-boundary-kb",
            "knowledge_base_ids": ["kb_1"],
        }
    )
    assert intent.intent == "knowledge_base_rag"
    assert plan.route_type == "rag"
    assert plan.rag_scope == "knowledge_base"


def test_file_conversion_does_not_get_stolen_by_uploaded_skill():
    _, intent, plan = _plan(
        {
            "message": "把这个文件转换成 Markdown",
            "conversation_id": "routing-boundary-convert",
            "files": [{"file_id": "file_1", "path": "storage/workspaces/u/c/uploads/a.txt"}],
        }
    )
    assert intent.intent == "file_conversion"
    assert plan.route_type == "skill"
    assert plan.skill_name == "file-converter"


def test_plain_csv_routes_to_table_analysis_not_raman(tmp_path: Path):
    path = tmp_path / "orders.csv"
    pd.DataFrame({"product": ["A", "B"], "sales": [10, 20]}).to_csv(path, index=False, encoding="utf-8")
    normalized, intent, plan = _plan(
        {
            "message": "统计每个商品的销售额",
            "conversation_id": "routing-boundary-table",
            "file_path": str(path),
        }
    )
    assert normalized.file_type == "table"
    assert intent.intent == "csv_analysis"
    assert plan.skill_name == "table-analysis"


def test_raman_csv_requires_raman_signal_or_user_intent(tmp_path: Path):
    path = tmp_path / "spectrum.csv"
    pd.DataFrame({"shift": [100, 200], "intensity": [1.0, 2.0]}).to_csv(path, index=False, encoding="utf-8")
    normalized, intent, plan = _plan(
        {
            "message": "分析这个 Raman 样品",
            "conversation_id": "routing-boundary-raman",
            "file_path": str(path),
        }
    )
    assert normalized.file_type == "raman"
    assert intent.intent == "raman_analysis"
    assert plan.skill_name == "raman_spectroscopy_skill"
