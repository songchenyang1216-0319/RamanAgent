from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any

import pandas as pd
from pandas.api.types import is_numeric_dtype


DEFAULT_LIMIT = 20
MAX_SAMPLE_VALUES = 10

COUNT_KEYWORDS = ("有多少条", "几条", "多少记录", "记录数", "数量是多少", "有多少行", "count", "number of records")
QUERY_KEYWORDS = ("列出来", "显示", "筛选", "找出", "查看这些记录", "哪些记录", "都列出来", "显示出来", "筛选出来")
GROUPBY_COUNT_KEYWORDS = ("每个", "各个", "分别", "分布")
DISTINCT_VALUE_KEYWORDS = ("有哪些", "有什么", "有啥", "都有哪些", "包括哪些", "包含哪些")
GROUPBY_STAT_KEYWORDS = ("总和", "合计", "平均", "均值", "最大", "最小", "中位数", "sum", "mean", "avg", "max", "min", "median")
MISSING_VALUE_KEYWORDS = ("缺失值", "空值", "为空", "检查空值")
VISUALIZE_KEYWORDS = ("画图", "可视化", "柱状图", "折线图", "趋势图", "散点图")
CLEAN_KEYWORDS = ("清洗", "删除重复行", "填充缺失值", "处理空值", "导出清洗后的")
SUMMARY_KEYWORDS = ("分析一下这个表格", "看看这个 csv", "总结一下这个文件", "分析一下这个csv", "分析一下这个文件")

COMPARISON_OPERATORS: tuple[tuple[str, str], ...] = (
    ("大于等于", "gte"),
    ("小于等于", "lte"),
    ("不等于", "neq"),
    ("不是", "neq"),
    ("等于", "eq"),
    ("包含", "contains"),
    ("大于", "gt"),
    ("小于", "lt"),
    ("==", "eq"),
    ("!=", "neq"),
    (">=", "gte"),
    ("<=", "lte"),
    (">", "gt"),
    ("<", "lt"),
    ("=", "eq"),
    ("为", "eq"),
    ("是", "eq"),
)

NULL_OPERATORS: tuple[tuple[str, str], ...] = (
    ("为空", "is_null"),
    ("是空的", "is_null"),
    ("空值", "is_null"),
    ("不为空", "not_null"),
    ("非空", "not_null"),
)

AGG_KEYWORDS = {
    "sum": ("总和", "合计", "总计", "求和", "sum"),
    "mean": ("平均", "均值", "平均值", "avg", "mean"),
    "max": ("最大", "最高", "max"),
    "min": ("最小", "最低", "min"),
    "median": ("中位数", "median"),
    "count": ("计数", "数量", "count"),
}

ALIAS_CANDIDATES = {
    "省份": ("province",),
    "省": ("province",),
    "地区": ("province", "region", "city"),
    "城市": ("city",),
    "市": ("city",),
    "订单状态": ("order_status",),
    "状态": ("order_status",),
    "商品名称": ("product_name",),
    "商品": ("product_name", "product_category"),
    "商品类别": ("product_category",),
    "类别": ("product_category",),
    "销售额": ("sales", "total_amount", "amount"),
    "金额": ("total_amount", "sales", "amount"),
    "数量": ("quantity",),
    "单价": ("unit_price",),
    "价格": ("unit_price",),
    "评分": ("customer_rating",),
    "会员": ("is_member",),
    "支付方式": ("payment_method",),
}

VALUE_SUFFIX_PATTERNS = (
    r"(记录|数据|行|条)$",
    r"(记录|数据|行|条)都列出来$",
    r"(记录|数据|行|条)列出来$",
    r"(记录|数据|行|条)显示出来$",
    r"(记录|数据|行|条)筛选出来$",
    r"都列出来$",
    r"列出来$",
    r"显示出来$",
    r"筛选出来$",
    r"有多少$",
    r"多少条$",
    r"几条$",
    r"有多少条记录$",
    r"有多少条$",
    r"数量是多少$",
)

VALUE_TRAILING_CLAUSE_PATTERNS = (
    r"(的)?[，,\s]*有多少.*$",
    r"(的)?[，,\s]*有几条.*$",
    r"(的)?[，,\s]*几条.*$",
    r"(的)?[，,\s]*多少条.*$",
    r"(的)?[，,\s]*数量是多少.*$",
    r"(的)?[，,\s]*前\s*\d+\s*条.*$",
    r"(的)?[，,\s]*(记录|数据|行|条)(都)?(列出来|显示出来|筛选出来).*$",
    r"(的)?[，,\s]*(都)?(列出来|显示出来|筛选出来).*$",
)

IMPLICIT_VALUE_PATTERNS = (
    r"有多少(?:条|行|记录)?(?:是|为)?(?P<value>.+?)(?:的)?[？?]?$",
    r"这里面有多少(?:条|行|记录)?(?:是|为)?(?P<value>.+?)(?:的)?[？?]?$",
    r"里面有多少(?:条|行|记录)?(?:是|为)?(?P<value>.+?)(?:的)?[？?]?$",
    r"多少(?:条|行|记录)?(?:是|为)?(?P<value>.+?)(?:的)?[？?]?$",
)


@dataclass
class TableFilter:
    column: str
    operator: str
    value: Any = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TableQueryPlan:
    action: str
    confidence: float
    filters: list[TableFilter] = field(default_factory=list)
    group_by: str | None = None
    target_column: str | None = None
    agg: str | None = None
    sort_by: str | None = None
    sort_order: str | None = None
    limit: int | None = None
    chart_type: str | None = None
    need_clarification: bool = False
    clarification_question: str | None = None
    reason: str = ""
    domain: str = "table_analysis"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["filters"] = [item.to_dict() for item in self.filters]
        return payload


@dataclass
class ColumnMention:
    raw_text: str
    column: str | None
    start: int
    end: int
    source: str
    ambiguous_candidates: list[str] = field(default_factory=list)


def normalize_filter_value(value: str) -> str:
    text = str(value or "").strip()
    text = text.strip("\"'“”‘’")
    text = text.replace("\u3000", " ").strip()
    text = re.sub(r"^[，。！？?!、\s]+", "", text)
    text = re.sub(r"[，。！？?!、\s]+$", "", text)
    for pattern in VALUE_TRAILING_CLAUSE_PATTERNS:
        text = re.sub(pattern, "", text)
    for pattern in VALUE_SUFFIX_PATTERNS:
        text = re.sub(pattern, "", text)
    text = text.strip().strip("\"'“”‘’")
    text = re.sub(r"[，。！？?!、\s]+$", "", text)
    while text.endswith(("的", "地", "得")) and len(text) > 1:
        text = text[:-1].rstrip()
    return text.strip()


class TableQueryPlanner:
    def __init__(self) -> None:
        self.alias_candidates = {str(key): tuple(value) for key, value in ALIAS_CANDIDATES.items()}
        self._current_df = pd.DataFrame()
        self._current_columns: list[str] = []

    def plan(self, user_message: str, df: pd.DataFrame) -> TableQueryPlan:
        text = str(user_message or "").strip()
        lowered = text.lower()
        columns = [str(column) for column in df.columns]
        self._current_df = df.copy()
        self._current_columns = columns
        if not columns:
            return self._clarify("当前表格没有识别到有效列名，请先确认文件内容。", 0.2, "表格缺少可用列名")

        if self._looks_like_summary(text, lowered):
            return TableQueryPlan(action="summarize_table", confidence=0.9, reason="用户是在做宽泛表格概览")

        filters_result = self._extract_filters(text, columns)
        if filters_result.get("clarify"):
            return self._clarify(filters_result["clarify"], 0.3, filters_result.get("reason") or "条件中的列名无法定位")
        filters = filters_result.get("filters", [])

        query_plan = self._plan_query_table(text, lowered, filters)
        if query_plan is not None:
            return query_plan

        count_plan = self._plan_count_records(text, lowered, filters)
        if count_plan is not None:
            return count_plan

        groupby_statistics_plan = self._plan_groupby_statistics(text, lowered, columns)
        if groupby_statistics_plan is not None:
            return groupby_statistics_plan

        groupby_count_plan = self._plan_groupby_count(text, lowered, columns)
        if groupby_count_plan is not None:
            return groupby_count_plan

        top_plan = self._plan_top_n(text, lowered, columns)
        if top_plan is not None:
            return top_plan

        missing_plan = self._plan_missing_value_check(text, lowered, columns)
        if missing_plan is not None:
            return missing_plan

        basic_plan = self._plan_basic_statistics(text, lowered, columns)
        if basic_plan is not None:
            return basic_plan

        if self._contains_any(text, VISUALIZE_KEYWORDS):
            return TableQueryPlan(action="visualize_table", confidence=0.82, chart_type=self._infer_chart_type(text), reason="用户希望对表格结果做可视化")

        if self._contains_any(text, CLEAN_KEYWORDS):
            return TableQueryPlan(action="clean_table", confidence=0.84, reason="用户希望进行表格清洗")

        unknown_candidate = self._extract_unknown_column_candidate(text, columns)
        if unknown_candidate:
            return self._clarify(f"没有找到 {unknown_candidate} 列。你是不是想问 {self._suggest_columns(columns)}？", 0.25, "用户提到的列名不存在")

        return self._clarify(
            "我还不能确定你想做计数、筛选、分组统计还是概览。你可以再具体一点，比如“省份是上海的有多少条记录”。",
            0.2,
            "意图不够明确",
        )

    def _plan_query_table(self, text: str, lowered: str, filters: list[TableFilter]) -> TableQueryPlan | None:
        if not filters:
            return None
        if self._contains_any(text, QUERY_KEYWORDS) or self._extract_limit(text) is not None:
            return TableQueryPlan(
                action="query_table",
                confidence=0.95,
                filters=filters,
                limit=self._extract_limit(text) or DEFAULT_LIMIT,
                reason="用户希望筛选并查看满足条件的记录",
            )
        return None

    def _plan_count_records(self, text: str, lowered: str, filters: list[TableFilter]) -> TableQueryPlan | None:
        if any(keyword in text for keyword in GROUPBY_COUNT_KEYWORDS):
            return None
        inferred_filters = filters or self._infer_filter_from_value_only(text)
        if not inferred_filters:
            return None
        if self._contains_any(text, COUNT_KEYWORDS) or re.search(r"有多少.*(条|行|记录)", text) or re.search(r"有多少.*是.+", text):
            return TableQueryPlan(
                action="count_records",
                confidence=0.95,
                filters=inferred_filters,
                reason="用户询问满足条件的记录数量",
            )
        return None

    def _plan_groupby_count(self, text: str, lowered: str, columns: list[str]) -> TableQueryPlan | None:
        ask_distribution = any(keyword in text for keyword in GROUPBY_COUNT_KEYWORDS) or re.search(r"按.+统计数量", text)
        ask_distinct_values = any(keyword in text for keyword in DISTINCT_VALUE_KEYWORDS)
        if self._detect_agg(text, lowered) is not None:
            return None
        group_by = self._find_groupby_column(text, columns)
        if group_by is None and ask_distinct_values:
            group_by = self._infer_distinct_column(text, columns)
        if group_by is None:
            return None
        if not ask_distribution and not ask_distinct_values:
            if not (
                text.startswith("按")
                or "列名是" in text
                or "列明是" in text
                or "分组" in text
                or "统计" in text
                or "分布" in text
            ):
                return None
        if not ask_distribution and not ask_distinct_values and group_by not in columns:
            return None
        return TableQueryPlan(
            action="groupby_count",
            confidence=0.92,
            group_by=group_by,
            limit=DEFAULT_LIMIT,
            reason="用户希望按某个字段统计每类数量",
        )

    def _plan_groupby_statistics(self, text: str, lowered: str, columns: list[str]) -> TableQueryPlan | None:
        agg = self._detect_agg(text, lowered)
        if agg is None:
            return None
        if not any(token in text for token in ("每个", "各个", "不同", "按", "分别")):
            return None
        group_by = self._find_groupby_column(text, columns)
        if group_by is None:
            return None
        target_column = self._find_target_column(text, columns, exclude={group_by})
        if target_column is None:
            return self._clarify(
                f"我识别到了分组字段 `{group_by}` 和聚合意图 `{agg}`，但还没找到要统计的目标列。你可以告诉我是哪个字段，比如 sales 或 quantity。",
                0.45,
                "缺少聚合目标列",
            )
        return TableQueryPlan(
            action="groupby_statistics",
            confidence=0.93,
            group_by=group_by,
            target_column=target_column,
            agg=agg,
            limit=DEFAULT_LIMIT,
            reason="用户希望按字段分组后做聚合统计",
        )

    def _plan_top_n(self, text: str, lowered: str, columns: list[str]) -> TableQueryPlan | None:
        if not self._contains_any(text, ("最高", "最低", "最大", "最小", "top", "排序", "从高到低", "从低到高")):
            return None
        sort_by = self._find_target_column(text, columns, exclude=set())
        if sort_by is None:
            return None
        limit = self._extract_limit(text) or 10
        action = "sort_table" if any(token in text for token in ("排序", "从高到低", "从低到高")) and "前" not in text else "top_n"
        sort_order = "asc" if any(token in text for token in ("最低", "最小", "从低到高")) else "desc"
        return TableQueryPlan(action=action, confidence=0.9, sort_by=sort_by, sort_order=sort_order, limit=limit, reason="用户希望按某一列排序或查看 Top N")

    def _plan_missing_value_check(self, text: str, lowered: str, columns: list[str]) -> TableQueryPlan | None:
        if not self._contains_any(text, MISSING_VALUE_KEYWORDS):
            return None
        target_column = self._find_target_column(text, columns, exclude=set())
        return TableQueryPlan(action="missing_value_check", confidence=0.92, target_column=target_column, reason="用户正在检查缺失值或空值")

    def _plan_basic_statistics(self, text: str, lowered: str, columns: list[str]) -> TableQueryPlan | None:
        if not any(keyword in text for keyword in ("基础统计", "均值", "平均值", "最大值", "最小值", "中位数")) and not any(keyword in lowered for keyword in ("mean", "avg", "max", "min", "median")):
            return None
        target_column = self._find_target_column(text, columns, exclude=set())
        agg = self._detect_agg(text, lowered)
        return TableQueryPlan(action="basic_statistics", confidence=0.88, target_column=target_column, agg=agg, reason="用户希望查看基础统计指标")

    def _extract_filters(self, text: str, columns: list[str]) -> dict[str, Any]:
        mention = self._find_best_column_mention(text, columns)
        if mention is None:
            return {"filters": []}
        if mention.column is None:
            return {"clarify": f"{mention.raw_text} 可能对应多个字段：{'、'.join(mention.ambiguous_candidates)}。你想用哪一列？", "reason": "别名映射到多个候选列"}

        tail = text[mention.end:].strip()
        for marker, operator in NULL_OPERATORS:
            if tail.startswith(marker):
                return {"filters": [TableFilter(column=mention.column, operator=operator, value=None)]}

        for marker, operator in COMPARISON_OPERATORS:
            if not tail.startswith(marker):
                continue
            raw_value = tail[len(marker):]
            value = normalize_filter_value(raw_value)
            if operator in {"is_null", "not_null"}:
                return {"filters": [TableFilter(column=mention.column, operator=operator, value=None)]}
            if not value:
                return {"clarify": f"我识别到了字段 `{mention.column}`，但没有看清筛选值。你可以再说一次，比如“{mention.raw_text}是上海”。", "reason": "缺少筛选值"}
            return {"filters": [TableFilter(column=mention.column, operator=operator, value=value)]}

        return {"filters": []}

    def _find_best_column_mention(self, text: str, columns: list[str]) -> ColumnMention | None:
        mentions: list[ColumnMention] = []
        for column in columns:
            start = text.find(str(column))
            while start >= 0:
                mentions.append(ColumnMention(raw_text=str(column), column=str(column), start=start, end=start + len(str(column)), source="column"))
                start = text.find(str(column), start + 1)

        for alias, targets in self.alias_candidates.items():
            start = text.find(alias)
            while start >= 0:
                existing = [candidate for candidate in targets if any(self._normalize_name(candidate) == self._normalize_name(column) for column in columns)]
                if len(existing) == 1:
                    mentions.append(ColumnMention(raw_text=alias, column=self._resolve_column_name(existing[0], columns), start=start, end=start + len(alias), source="alias"))
                elif len(existing) > 1:
                    mentions.append(ColumnMention(raw_text=alias, column=None, start=start, end=start + len(alias), source="alias", ambiguous_candidates=[self._resolve_column_name(item, columns) or item for item in existing]))
                start = text.find(alias, start + 1)

        if not mentions:
            return None
        mentions.sort(key=lambda item: (item.start, 0 if item.source == "column" else 1, -(item.end - item.start)))
        return mentions[0]

    def _find_groupby_column(self, text: str, columns: list[str]) -> str | None:
        if "按" in text:
            after_by = text.split("按", 1)[1]
            for candidate in self._all_candidate_terms(columns):
                if after_by.startswith(candidate):
                    mention = self._find_best_column_mention(candidate, columns)
                    if mention and mention.column:
                        return mention.column
        for keyword in ("每个", "各个", "不同", "按", "分布"):
            if keyword not in text:
                continue
            index = text.find(keyword) + len(keyword)
            fragment = text[index:]
            mention = self._find_best_column_mention(fragment, columns)
            if mention and mention.column:
                return mention.column
        mention = self._find_best_column_mention(text, columns)
        return mention.column if mention and mention.column else None

    def _find_target_column(self, text: str, columns: list[str], exclude: set[str]) -> str | None:
        for column in columns:
            if str(column) in exclude:
                continue
            if str(column) in text:
                return str(column)
        for alias, targets in self.alias_candidates.items():
            if alias not in text:
                continue
            existing = [self._resolve_column_name(candidate, columns) for candidate in targets]
            existing = [item for item in existing if item and item not in exclude]
            if len(existing) == 1:
                return existing[0]
        return None

    def _infer_distinct_column(self, text: str, columns: list[str]) -> str | None:
        mention = self._find_best_column_mention(text, columns)
        if mention and mention.column:
            return mention.column
        for preferred in ("province", "city", "order_status", "product_category"):
            resolved = self._resolve_column_name(preferred, columns)
            if resolved and any(alias in text for alias, targets in self.alias_candidates.items() if preferred in targets):
                return resolved
        return None

    def _find_column_from_text(self, text: str, columns: list[str]) -> str | None:
        mention = self._find_best_column_mention(text, columns)
        return mention.column if mention and mention.column else None

    def _infer_filter_from_value_only(self, text: str) -> list[TableFilter]:
        candidate_value = ""
        for pattern in IMPLICIT_VALUE_PATTERNS:
            match = re.search(pattern, text)
            if match:
                candidate_value = normalize_filter_value(match.group("value"))
                if candidate_value:
                    break
        if not candidate_value:
            return []
        matches: list[str] = []
        for column in self._current_columns:
            series = self._current_df[column]
            normalized_series = series.fillna("").astype(str).map(normalize_filter_value)
            exact_count = int((normalized_series.str.casefold() == candidate_value.casefold()).sum())
            if exact_count > 0:
                matches.append(str(column))
                continue
            contains_count = int(normalized_series.str.contains(re.escape(candidate_value), case=False, na=False, regex=True).sum())
            if contains_count > 0:
                matches.append(str(column))
        if len(matches) == 1:
            return [TableFilter(column=matches[0], operator="eq", value=candidate_value)]
        return []

    def _detect_agg(self, text: str, lowered: str) -> str | None:
        for agg, keywords in AGG_KEYWORDS.items():
            if any(keyword in text for keyword in keywords) or any(keyword in lowered for keyword in keywords):
                return agg
        return None

    def _infer_chart_type(self, text: str) -> str | None:
        for chart_type in ("柱状图", "折线图", "饼图", "散点图"):
            if chart_type in text:
                return chart_type
        return None

    def _extract_limit(self, text: str) -> int | None:
        match = re.search(r"前\s*(\d+)\s*条", text)
        if match:
            return int(match.group(1))
        match = re.search(r"top\s*(\d+)", text, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
        return None

    def _extract_unknown_column_candidate(self, text: str, columns: list[str]) -> str | None:
        match = re.search(r"([A-Za-z_][A-Za-z0-9_]*|[\u4e00-\u9fa5]{1,8})\s*(是|为|等于|不是|不等于|包含|大于等于|小于等于|大于|小于|=|==|!=|>=|<=|>|<|为空|不为空|非空)", text)
        if not match:
            return None
        candidate = match.group(1).strip()
        if any(noise in candidate for noise in ("这个文件", "所有", "全部", "记录", "数据", "这里面有多少", "里面有多少", "有多少")):
            return None
        if self._find_column_from_text(candidate, columns):
            return None
        if candidate in self.alias_candidates:
            existing = [item for item in self.alias_candidates[candidate] if self._resolve_column_name(item, columns)]
            if existing:
                return None
        return candidate

    def _resolve_column_name(self, expected: str, columns: list[str]) -> str | None:
        for column in columns:
            if self._normalize_name(column) == self._normalize_name(expected):
                return str(column)
        return None

    def _all_candidate_terms(self, columns: list[str]) -> list[str]:
        return sorted(set([*columns, *self.alias_candidates.keys()]), key=len, reverse=True)

    def _looks_like_summary(self, text: str, lowered: str) -> bool:
        if any(keyword in text for keyword in SUMMARY_KEYWORDS):
            return True
        if any(keyword in text for keyword in ("主要记录的是什么内容", "这个文件里有什么", "这个文件是什么内容", "看看这个文件里有什么")):
            return True
        if self._contains_any(text, QUERY_KEYWORDS + COUNT_KEYWORDS + GROUPBY_COUNT_KEYWORDS + MISSING_VALUE_KEYWORDS + CLEAN_KEYWORDS + VISUALIZE_KEYWORDS):
            return False
        if self._detect_agg(text, lowered) is not None:
            return False
        if self._find_best_column_mention(text, []) is not None:
            return False
        return any(keyword in text for keyword in ("分析一下", "总结一下", "看看这个")) and any(keyword in lowered for keyword in ("csv", "excel", "表格", "文件"))

    def _contains_any(self, text: str, keywords: tuple[str, ...]) -> bool:
        return any(keyword in text for keyword in keywords)

    def _normalize_name(self, value: Any) -> str:
        return "".join(str(value or "").strip().lower().replace("_", " ").split())

    def _suggest_columns(self, columns: list[str]) -> str:
        return "、".join(columns[:5]) if columns else "已有字段"

    def _clarify(self, question: str, confidence: float, reason: str) -> TableQueryPlan:
        return TableQueryPlan(action="clarify", confidence=confidence, need_clarification=True, clarification_question=question, reason=reason)


def build_table_schema(df: pd.DataFrame) -> dict[str, Any]:
    schema_columns: list[dict[str, Any]] = []
    for column in df.columns:
        series = df[column]
        non_null = series.dropna()
        sample_values = [str(item).strip() for item in non_null.astype(str).head(MAX_SAMPLE_VALUES).tolist() if str(item).strip()]
        dtype = "numeric" if is_numeric_dtype(series) else "string"
        schema_columns.append({"name": str(column), "dtype": dtype, "sample_values": sample_values, "null_count": int(series.isna().sum())})
    return {"row_count": int(len(df)), "column_count": int(len(df.columns)), "columns": schema_columns}
