from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.main import app


def _write_table(tmp_path: Path) -> Path:
    path = tmp_path / "orders.csv"
    pd.DataFrame(
        {
            "province": ["上海", "北京", "上海", "广东"],
            "city": ["上海", "北京", "上海", "深圳"],
            "sales": [100, 200, 150, 120],
            "customer_rating": [5, None, 4, None],
        }
    ).to_csv(path, index=False, encoding="utf-8")
    return path


def test_agent_routes_uploaded_table_to_count_records(tmp_path):
    path = _write_table(tmp_path)
    client = TestClient(app)
    response = client.post(
        "/api/agent/chat",
        data={"message": "province 是上海的有多少条记录？"},
        files={"file": (path.name, path.read_bytes(), "text/csv")},
    )
    payload = response.json()
    assert payload["success"] is True
    assert payload["skill_name"] == "data-analysis-skill"
    assert payload["action_name"] == "count_records"
    assert payload["tool_info"]["action"] == "count_records"
    assert payload["result"]["data"]["matched_count"] == 2
    assert payload["result"]["data"]["total_count"] == 4
    assert "占比" in payload["reply"]
    assert "字段结构" not in payload["reply"]


def test_agent_routes_uploaded_table_to_query_table_with_alias(tmp_path):
    path = _write_table(tmp_path)
    client = TestClient(app)
    response = client.post(
        "/api/agent/chat",
        data={"message": "把这个文件中所有省份是北京的记录都列出来"},
        files={"file": (path.name, path.read_bytes(), "text/csv")},
    )
    payload = response.json()
    assert payload["success"] is True
    assert payload["skill_name"] == "data-analysis-skill"
    assert payload["action_name"] == "query_table"
    assert payload["tool_info"]["action"] == "query_table"
    assert payload["result"]["data"]["matched_count"] == 1
    assert len(payload["result"]["data"]["preview"]) == 1
    assert "没有找到 把这个文件中所有省份 列" not in payload["reply"]


def test_agent_routes_distinct_province_question_to_groupby_count(tmp_path):
    path = _write_table(tmp_path)
    client = TestClient(app)
    response = client.post(
        "/api/agent/chat",
        data={"message": "这个文件有啥省份？"},
        files={"file": (path.name, path.read_bytes(), "text/csv")},
    )
    payload = response.json()
    assert payload["success"] is True
    assert payload["skill_name"] == "data-analysis-skill"
    assert payload["action_name"] == "groupby_count"
    assert payload["tool_info"]["action"] == "groupby_count"


def test_agent_routes_ambiguous_or_missing_column_case_to_clarify_instead_of_csv_summary(tmp_path):
    path = _write_table(tmp_path)
    client = TestClient(app)
    response = client.post(
        "/api/agent/chat",
        data={"message": "abc 是上海的有多少条记录"},
        files={"file": (path.name, path.read_bytes(), "text/csv")},
    )
    payload = response.json()
    assert payload["skill_name"] == "data-analysis-skill"
    assert payload["action_name"] == "clarify"
    assert payload["success"] is True
    assert payload["data"]["need_clarification"] is True
    assert "字段结构" not in payload["reply"]


def test_agent_reuses_last_uploaded_table_for_followup_text_query(tmp_path):
    path = _write_table(tmp_path)
    client = TestClient(app)
    first = client.post(
        "/api/agent/chat",
        data={"message": "请先分析这个文件"},
        files={"file": (path.name, path.read_bytes(), "text/csv")},
    ).json()
    session_id = first.get("session_id") or first.get("conversation_id")
    assert session_id

    followup = client.post(
        "/api/agent/chat",
        json={"message": "按城市", "session_id": session_id, "conversation_id": session_id},
    ).json()
    assert followup["success"] is True
    assert followup["skill_name"] == "data-analysis-skill"
    assert followup["action_name"] == "groupby_count"
    assert followup["tool_info"]["action"] == "groupby_count"
    assert "city" in str(followup["reply"]).lower() or "城市" in str(followup["reply"])
