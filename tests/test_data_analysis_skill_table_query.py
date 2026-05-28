from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.skills.registry import execute_skill


def _write_table(tmp_path: Path) -> Path:
    path = tmp_path / "orders.csv"
    pd.DataFrame(
        {
            "province": ["上海", "北京", "上海", "广东"],
            "city": ["上海", "北京", "上海", "深圳"],
            "sales": [100, 200, 150, 120],
            "customer_rating": [5, None, 4, None],
            "order_status": ["已完成", "待支付", "已完成", "已发货"],
            "quantity": [1, 2, 3, 4],
        }
    ).to_csv(path, index=False, encoding="utf-8")
    return path


def test_count_records_result(tmp_path):
    path = _write_table(tmp_path)
    result = execute_skill("data-analysis-skill", action_name="count_records", file_path=str(path), message="province 是上海的有多少条记录？")
    assert result.success is True
    assert result.action_name == "count_records"
    assert result.data["data"]["matched_count"] == 2
    assert result.data["data"]["total_count"] == 4
    assert round(result.data["data"]["ratio"], 4) == 0.5
    assert "占比" in result.data["markdown"]


def test_query_table_result(tmp_path):
    path = _write_table(tmp_path)
    result = execute_skill("data-analysis-skill", action_name="query_table", file_path=str(path), message="筛选 province 是上海的前20条")
    assert result.success is True
    assert result.action_name == "query_table"
    assert result.data["data"]["matched_count"] == 2
    assert len(result.data["data"]["preview"]) == 2
    assert len(result.data["data"]["preview"]) <= 20


def test_query_table_alias_result(tmp_path):
    path = _write_table(tmp_path)
    result = execute_skill("data-analysis-skill", action_name="query_table", file_path=str(path), message="把这个文件中所有省份是北京的记录都列出来")
    assert result.success is True
    assert result.action_name == "query_table"
    assert result.data["data"]["matched_count"] == 1
    assert result.data["debug"]["normalized_value"] == "北京"
    assert result.data["data"]["filters"][0]["column"] == "province"


def test_groupby_statistics_result(tmp_path):
    path = _write_table(tmp_path)
    result = execute_skill("data-analysis-skill", action_name="groupby_statistics", file_path=str(path), message="每个 province 的 sales 总和是多少？")
    assert result.success is True
    assert result.action_name == "groupby_statistics"
    rows = result.data["data"]["rows"]
    assert any(row["group"] == "上海" and row["value"] == 250.0 for row in rows)


def test_missing_value_check_target_column(tmp_path):
    path = _write_table(tmp_path)
    result = execute_skill("data-analysis-skill", action_name="missing_value_check", file_path=str(path), message="customer_rating 有多少空值？")
    assert result.success is True
    assert result.data["data"]["target_column"] == "customer_rating"
    assert result.data["data"]["missing_count"] == 2


def test_value_not_found_returns_zero_not_error(tmp_path):
    path = _write_table(tmp_path)
    result = execute_skill("data-analysis-skill", action_name="count_records", file_path=str(path), message="province 是火星的有多少条？")
    assert result.success is True
    assert result.data["data"]["matched_count"] == 0
    assert "火星" in result.data["markdown"]


def test_count_records_alias_cleans_trailing_de(tmp_path):
    path = _write_table(tmp_path)
    result = execute_skill("data-analysis-skill", action_name="count_records", file_path=str(path), message="省份是上海的，有多少条记录")
    assert result.success is True
    assert result.action_name == "count_records"
    assert result.data["data"]["matched_count"] == 2
    assert result.data["debug"]["normalized_value"] == "上海"
    assert "上海的" not in result.data["markdown"]


def test_zero_match_returns_cross_column_suggestion(tmp_path):
    path = tmp_path / "orders.csv"
    pd.DataFrame(
        {
            "province": ["上海", "江苏", "广东", "浙江"],
            "city": ["上海", "北京", "北京", "杭州"],
            "order_status": ["已完成", "待支付", "已完成", "已发货"],
        }
    ).to_csv(path, index=False, encoding="utf-8")
    result = execute_skill("data-analysis-skill", action_name="query_table", file_path=str(path), message="省份是北京的记录都列出来")
    assert result.success is True
    assert result.action_name == "query_table"
    assert result.data["data"]["matched_count"] == 0
    suggestion = result.data["data"]["diagnosis"]["suggestion"]
    assert "province 列中没有“北京”" in suggestion
    assert "city 列中存在“北京”" in suggestion
