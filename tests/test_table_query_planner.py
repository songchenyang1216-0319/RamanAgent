from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.skills.table_query_planner import TableQueryPlanner


def _sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "province": ["上海", "北京", "上海", "广东"],
            "city": ["上海", "北京", "上海", "深圳"],
            "sales": [100, 200, 150, 120],
            "customer_rating": [5, None, 4, None],
            "order_status": ["已完成", "待支付", "已完成", "已发货"],
            "quantity": [1, 2, 3, 4],
        }
    )


def test_count_records_chinese_is():
    plan = TableQueryPlanner().plan("province 是上海的有多少条记录？", _sample_df())
    assert plan.action == "count_records"
    assert plan.filters[0].column == "province"
    assert plan.filters[0].value == "上海"


def test_count_records_equal_sign():
    plan = TableQueryPlanner().plan("province=上海有几条？", _sample_df())
    assert plan.action == "count_records"
    assert plan.filters[0].column == "province"
    assert plan.filters[0].value == "上海"


def test_count_records_alias():
    plan = TableQueryPlanner().plan("省份是上海的有多少条？", _sample_df())
    assert plan.action == "count_records"
    assert plan.filters[0].column == "province"
    assert plan.filters[0].value == "上海"


def test_query_table_alias_with_long_chinese_prefix():
    plan = TableQueryPlanner().plan("把这个文件中所有省份是北京的记录都列出来", _sample_df())
    assert plan.action == "query_table"
    assert plan.filters[0].column == "province"
    assert plan.filters[0].value == "北京"


def test_groupby_count_distinct_alias_question():
    plan = TableQueryPlanner().plan("这个文件有啥省份？", _sample_df())
    assert plan.action == "groupby_count"
    assert plan.group_by == "province"


def test_groupby_count_short_followup_phrase():
    plan = TableQueryPlanner().plan("按城市", _sample_df())
    assert plan.action == "groupby_count"
    assert plan.group_by == "city"


def test_count_records_alias_with_suffix_cleanup():
    plan = TableQueryPlanner().plan("省份是上海的，有多少条记录", _sample_df())
    assert plan.action == "count_records"
    assert plan.filters[0].column == "province"
    assert plan.filters[0].value == "上海"


def test_groupby_count():
    plan = TableQueryPlanner().plan("每个 province 有多少条？", _sample_df())
    assert plan.action == "groupby_count"
    assert plan.group_by == "province"


def test_groupby_statistics():
    plan = TableQueryPlanner().plan("每个 province 的 sales 总和是多少？", _sample_df())
    assert plan.action == "groupby_statistics"
    assert plan.group_by == "province"
    assert plan.target_column == "sales"
    assert plan.agg == "sum"


def test_query_table():
    plan = TableQueryPlanner().plan("筛选 province 是上海的前20条", _sample_df())
    assert plan.action == "query_table"
    assert plan.limit == 20
    assert plan.filters[0].column == "province"
    assert plan.filters[0].value == "上海"


def test_top_n():
    plan = TableQueryPlanner().plan("销售额最高的前10条", _sample_df())
    assert plan.action == "top_n"
    assert plan.sort_by == "sales"
    assert plan.sort_order == "desc"
    assert plan.limit == 10


def test_missing_value_check():
    plan = TableQueryPlanner().plan("customer_rating 有多少空值？", _sample_df())
    assert plan.action == "missing_value_check"
    assert plan.target_column == "customer_rating"


def test_summarize_table():
    plan = TableQueryPlanner().plan("分析一下这个表格", _sample_df())
    assert plan.action == "summarize_table"


def test_clarify_when_column_missing():
    plan = TableQueryPlanner().plan("abc 是上海的有多少条？", _sample_df())
    assert plan.action == "clarify"
    assert plan.need_clarification is True
    assert "abc" in (plan.clarification_question or "")


def test_value_not_found_keeps_exact_value():
    plan = TableQueryPlanner().plan("province 是火星的有多少条？", _sample_df())
    assert plan.action == "count_records"
    assert plan.filters[0].column == "province"
    assert plan.filters[0].value == "火星"


def test_implicit_value_only_count_can_infer_unique_column():
    df = pd.DataFrame(
        {
            "province": ["上海", "广东", "浙江"],
            "city": ["上海", "北京", "深圳"],
        }
    )
    plan = TableQueryPlanner().plan("这里面有多少是北京的？", df)
    assert plan.action == "count_records"
    assert plan.filters[0].column == "city"
    assert plan.filters[0].value == "北京"
