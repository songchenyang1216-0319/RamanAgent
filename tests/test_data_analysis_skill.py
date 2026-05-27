from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.agent.agent_router import _select_skill_route
from backend.main import app
from backend.skills.data_analysis_skill import infer_data_analysis_action
from backend.skills.registry import execute_skill, list_skills


def _write_csv(tmp_path: Path, name: str = "scores.csv") -> Path:
    df = pd.DataFrame(
        {
            "student": ["Alice", "Bob", "Bob", None],
            "class": ["A", "A", "B", "B"],
            "score": [88, 92, 75, 81],
            "price": [10.5, 11.0, 9.8, None],
        }
    )
    path = tmp_path / name
    df.to_csv(path, index=False, encoding="utf-8")
    return path


def _write_xlsx(tmp_path: Path, name: str = "sales.xlsx") -> Path:
    df = pd.DataFrame(
        {
            "month": ["2026-01", "2026-02", "2026-03"],
            "sales": [120, 140, 135],
            "region": ["East", "West", "East"],
        }
    )
    path = tmp_path / name
    df.to_excel(path, index=False, sheet_name="Sheet1")
    return path


def _write_raman_csv(tmp_path: Path, name: str = "raman.csv") -> Path:
    df = pd.DataFrame(
        {
            "wavenumber": [400, 450, 500],
            "intensity": [0.12, 0.2, 0.18],
        }
    )
    path = tmp_path / name
    df.to_csv(path, index=False, encoding="utf-8")
    return path


def test_data_analysis_skill_is_listed():
    payload = list_skills(include_actions=True)
    names = {item.get("name") for item in payload.get("skills") or []}
    assert "data-analysis-skill" in names
    target = next(item for item in payload["skills"] if item.get("name") == "data-analysis-skill")
    action_names = {action.get("name") for action in target.get("actions") or []}
    assert "inspect_table" in action_names
    assert "chart_suggestion" in action_names


def test_csv_is_routed_to_data_analysis(tmp_path):
    csv_path = _write_csv(tmp_path)
    matched_skill, matched_action, route_info = _select_skill_route(
        "总结一下这个表格，看看字段和缺失值",
        has_file=True,
        file_suffix=".csv",
        file_path=csv_path,
    )
    assert matched_skill == "data-analysis-skill"
    assert matched_action in {"simple_query_table", "summarize_table", "missing_value_check"}
    assert route_info["route"] == "table_data_analysis_route"


def test_question_about_file_content_routes_to_simple_query(tmp_path):
    csv_path = _write_csv(tmp_path)
    matched_skill, matched_action, route_info = _select_skill_route(
        "这个文件主要记录的是什么内容？",
        has_file=True,
        file_suffix=".csv",
        file_path=csv_path,
    )
    assert matched_skill == "data-analysis-skill"
    assert matched_action == "simple_query_table"
    assert route_info["route"] == "table_data_analysis_route"
    assert infer_data_analysis_action("这个文件主要记录的是什么内容？") == "simple_query_table"


def test_xlsx_is_routed_to_data_analysis(tmp_path):
    xlsx_path = _write_xlsx(tmp_path)
    matched_skill, matched_action, route_info = _select_skill_route(
        "帮我分析一下这个 Excel 表格的主要内容",
        has_file=True,
        file_suffix=".xlsx",
        file_path=xlsx_path,
    )
    assert matched_skill == "data-analysis-skill"
    assert route_info["route"] == "table_data_analysis_route"


def test_plain_csv_will_not_enter_raman(tmp_path):
    csv_path = _write_csv(tmp_path)
    matched_skill, _, _ = _select_skill_route(
        "这个表格主要讲什么",
        has_file=True,
        file_suffix=".csv",
        file_path=csv_path,
    )
    assert matched_skill == "data-analysis-skill"


def test_raman_keywords_and_csv_will_enter_raman(tmp_path):
    csv_path = _write_csv(tmp_path)
    matched_skill, matched_action, route_info = _select_skill_route(
        "这是拉曼光谱数据，帮我做峰位和基线分析",
        has_file=True,
        file_suffix=".csv",
        file_path=csv_path,
    )
    assert matched_skill == "raman_spectroscopy_skill"
    assert matched_action == "predict_methanol_concentration"
    assert route_info["route"] == "table_raman_route"


def test_data_analysis_skill_returns_metadata_and_columns(tmp_path):
    csv_path = _write_csv(tmp_path)
    result = execute_skill("data-analysis-skill", action_name="inspect_table", file_path=str(csv_path), message="检查表格字段")
    metadata = result.data["metadata"]
    assert result.success is True
    assert metadata["rows"] == 4
    assert metadata["columns"] == 4
    assert "student" in metadata["column_names"]
    assert "score" in metadata["numeric_columns"]
    assert "student" in metadata["categorical_columns"]


def test_missing_value_and_statistics_are_returned(tmp_path):
    csv_path = _write_csv(tmp_path)
    result = execute_skill("data-analysis-skill", action_name="basic_statistics", file_path=str(csv_path), message="做统计")
    assert result.success is True
    assert result.data["quality"]["missing_cells"] >= 1
    assert result.data["statistics"]["numeric_summary"]["score"]["max"] == 92.0
    assert "class" in result.data["statistics"]["categorical_summary"]


def test_chart_suggestion_is_returned(tmp_path):
    xlsx_path = _write_xlsx(tmp_path)
    result = execute_skill("data-analysis-skill", action_name="chart_suggestion", file_path=str(xlsx_path), message="这个数据适合画什么图")
    assert result.success is True
    suggestions = result.data["statistics"]["chart_suggestions"]
    assert suggestions
    assert any("折线图" in item or "柱状图" in item or "散点图" in item for item in suggestions)


def test_different_actions_return_different_markdown_focus(tmp_path):
    csv_path = _write_csv(tmp_path)
    inspect_result = execute_skill("data-analysis-skill", action_name="inspect_table", file_path=str(csv_path), message="告诉我字段和行列")
    missing_result = execute_skill("data-analysis-skill", action_name="missing_value_check", file_path=str(csv_path), message="检查缺失值")
    assert inspect_result.success is True
    assert missing_result.success is True
    assert inspect_result.data["analysis_markdown"] != missing_result.data["analysis_markdown"]
    assert "表格结构检查结果" in inspect_result.data["analysis_markdown"]
    assert "缺失值与数据质量检查结果" in missing_result.data["analysis_markdown"]


def test_encoding_error_returns_friendly_message(tmp_path, monkeypatch):
    csv_path = tmp_path / "broken.csv"
    csv_path.write_bytes(b"\xff\xfe\xfd\xfc")

    def always_fail(*args, **kwargs):
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad")

    monkeypatch.setattr("backend.skills.data_analysis_skill.pd.read_csv", always_fail)
    result = execute_skill("data-analysis-skill", action_name="inspect_table", file_path=str(csv_path), message="帮我看一下")
    assert result.success is False
    assert "编码不兼容" in result.summary


def test_empty_csv_will_not_crash_backend(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")
    result = execute_skill("data-analysis-skill", action_name="summarize_table", file_path=str(path), message="总结一下")
    assert result.success is False
    assert "表格为空" in result.data["quality"]["warnings"][0] or "为空" in result.summary


def test_disabled_data_analysis_skill_returns_friendly_prompt(tmp_path, monkeypatch):
    csv_path = _write_csv(tmp_path)
    client = TestClient(app)
    real_loader = __import__("backend.skills.registry", fromlist=["_load_skills_config"])._load_skills_config

    def fake_load():
        config, error = real_loader()
        config["skills"]["data-analysis-skill"]["enabled"] = False
        return config, error

    monkeypatch.setattr("backend.skills.registry._load_skills_config", fake_load)
    response = client.post(
        "/api/agent/chat",
        data={"message": "总结一下这个表格"},
        files={"file": (csv_path.name, csv_path.read_bytes(), "text/csv")},
    )
    payload = response.json()
    assert payload["success"] is False
    assert "data-analysis-skill" in payload["error_message"] or "表格数据分析 Skill" in payload["reply"]


def test_disabled_data_analysis_action_returns_friendly_prompt(tmp_path, monkeypatch):
    csv_path = _write_csv(tmp_path)
    client = TestClient(app)
    real_loader = __import__("backend.skills.registry", fromlist=["_load_skills_config"])._load_skills_config

    def fake_load():
        config, error = real_loader()
        config["skills"]["data-analysis-skill"]["enabled"] = True
        config["skills"]["data-analysis-skill"]["actions"]["missing_value_check"] = False
        return config, error

    monkeypatch.setattr("backend.skills.registry._load_skills_config", fake_load)
    response = client.post(
        "/api/agent/chat",
        data={"message": "帮我检查这个表有没有缺失值"},
        files={"file": (csv_path.name, csv_path.read_bytes(), "text/csv")},
    )
    payload = response.json()
    assert payload["success"] is False
    assert "missing_value_check" in payload["error_message"] or "禁用" in payload["reply"]


def test_raman_table_signal_without_keywords_can_route_to_raman(tmp_path):
    csv_path = _write_raman_csv(tmp_path)
    matched_skill, matched_action, route_info = _select_skill_route(
        "帮我看一下这个文件",
        has_file=True,
        file_suffix=".csv",
        file_path=csv_path,
    )
    assert matched_skill == "raman_spectroscopy_skill"
    assert matched_action == "predict_methanol_concentration"
    assert route_info["route"] == "table_raman_route"
