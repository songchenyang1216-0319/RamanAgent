from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any
import math
import re
import warnings

import pandas as pd
from pandas.api.types import is_datetime64_any_dtype, is_numeric_dtype

from .base import BaseSkill, SkillResult
from .table_query_planner import TableFilter, TableQueryPlan, TableQueryPlanner, build_table_schema, normalize_filter_value


TABLE_FILE_SUFFIXES = {".csv", ".xlsx", ".xls"}
CSV_ENCODINGS = ("utf-8", "utf-8-sig", "gbk", "gb18030")
PREVIEW_ROWS = 20
MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024
RAMAN_TABLE_HINTS = (
    "raman",
    "sers",
    "shift",
    "intensity",
    "wavenumber",
    "wave_number",
    "cm-1",
    "cm^-1",
    "spectrum",
    "spectra",
    "peak",
    "baseline",
    "methanol",
    "光谱",
    "拉曼",
    "峰位",
    "峰强",
    "甲醇",
    "浓度",
)
RAMAN_MESSAGE_KEYWORDS = (
    "raman",
    "拉曼",
    "sers",
    "光谱",
    "谱图",
    "峰位",
    "峰强",
    "基线",
    "荧光背景",
    "去噪",
    "归一化",
    "甲醇",
    "浓度",
    "预测",
    "光谱分类",
    "光谱回归",
)
DATA_ANALYSIS_MESSAGE_KEYWORDS = (
    "总结表格",
    "表格内容",
    "统计",
    "字段",
    "缺失值",
    "重复值",
    "数据清洗",
    "画图",
    "可视化",
    "平均值",
    "最大值",
    "最小值",
    "分类统计",
    "销售",
    "成绩",
    "岗位",
    "价格",
    "财务",
    "用户数据",
    "普通数据",
)

ACTION_ALIASES = {
    "simple_query_table": "query_table",
    "categorical_summary": "groupby_count",
    "chart_suggestion": "visualize_table",
    "export_clean_preview": "clean_table",
}


class TableLoadResult:
    def __init__(
        self,
        *,
        df: pd.DataFrame,
        table_type: str,
        encoding: str | None,
        sheet_name: str | None,
        sheet_names: list[str],
        warnings: list[str],
    ) -> None:
        self.df = df
        self.table_type = table_type
        self.encoding = encoding
        self.sheet_name = sheet_name
        self.sheet_names = sheet_names
        self.warnings = warnings


def infer_data_analysis_action(message: str, default_action: str = "summarize_table") -> str:
    normalized = str(message or "").strip().lower()
    if any(keyword in normalized for keyword in ("多少条", "几条", "有多少行", "记录数", "数量是多少")):
        return "count_records"
    if any(keyword in normalized for keyword in ("每个", "各个", "分布", "value counts", "按")) and "多少" in normalized:
        return "groupby_count"
    if any(keyword in normalized for keyword in ("总和", "平均值", "均值", "最大值", "最小值", "sum", "mean", "avg", "max", "min", "median")):
        return "groupby_statistics"
    if any(keyword in normalized for keyword in ("筛选", "显示", "列出", "找出", "看看", "前20条", "前 20 条")):
        return "query_table"
    if any(keyword in normalized for keyword in ("最高", "最低", "top", "排序", "从高到低", "从低到高")):
        return "top_n"
    if any(keyword in normalized for keyword in ("缺失值", "空值", "为空", "空的")):
        return "missing_value_check"
    if any(keyword in normalized for keyword in ("基础统计", "均值", "平均值", "最大值", "最小值")):
        return "basic_statistics"
    if any(keyword in normalized for keyword in ("画图", "可视化", "柱状图", "折线图")):
        return "visualize_table"
    if any(keyword in normalized for keyword in ("清洗", "删除重复", "填充缺失值", "处理空值")):
        return "clean_table"
    if any(keyword in normalized for keyword in ("字段", "列名", "结构", "行数", "列数", "inspect")):
        return "inspect_table"
    return default_action


def is_supported_table_suffix(file_suffix: str | None) -> bool:
    return str(file_suffix or "").lower() in TABLE_FILE_SUFFIXES


def _normalize_name(value: object) -> str:
    return " ".join(str(value or "").strip().lower().replace("_", " ").split())


def detect_raman_table_signal(file_path: str | Path | None) -> dict[str, Any]:
    path = Path(str(file_path or "")).expanduser()
    if not path.exists() or not path.is_file() or not is_supported_table_suffix(path.suffix):
        return {"is_raman": False, "reason": "file_not_supported", "matched_hints": []}
    try:
        load_result = load_table_file(path, preview_only=True)
    except Exception as exc:  # pragma: no cover
        return {"is_raman": False, "reason": f"preview_failed:{type(exc).__name__}", "matched_hints": []}

    df = load_result.df
    column_names = [_normalize_name(column) for column in df.columns]
    preview_text = " ".join(_normalize_name(value) for row in df.head(5).fillna("").astype(str).values.tolist() for value in row)
    matched_hints = sorted({hint for hint in RAMAN_TABLE_HINTS if hint in " ".join(column_names) or hint in preview_text})
    shift_like = any(token in " ".join(column_names) for token in ("shift", "wavenumber", "cm-1", "cm^-1", "波数"))
    intensity_like = any(token in " ".join(column_names) for token in ("intensity", "强度", "absorbance"))
    is_raman = (shift_like and intensity_like) or len(matched_hints) >= 2
    return {
        "is_raman": bool(is_raman),
        "reason": "raman_column_hints" if is_raman else "no_raman_signal",
        "matched_hints": matched_hints,
        "column_names": [str(column) for column in df.columns],
    }


def load_table_file(file_path: str | Path, preview_only: bool = False) -> TableLoadResult:
    path = Path(str(file_path)).expanduser()
    if not path.exists():
        raise FileNotFoundError("文件不存在。")
    suffix = path.suffix.lower()
    if suffix not in TABLE_FILE_SUFFIXES:
        raise ValueError("文件类型不受支持。")
    if path.stat().st_size > MAX_FILE_SIZE_BYTES:
        raise ValueError("文件过大，当前仅支持 25MB 以内的表格文件。")

    if suffix == ".csv":
        last_error = ""
        for encoding in CSV_ENCODINGS:
            try:
                df = pd.read_csv(path, encoding=encoding, nrows=PREVIEW_ROWS if preview_only else None)
                return TableLoadResult(df=df, table_type="csv", encoding=encoding, sheet_name=None, sheet_names=[], warnings=[])
            except UnicodeDecodeError as exc:
                last_error = str(exc)
                continue
            except pd.errors.EmptyDataError:
                return TableLoadResult(df=pd.DataFrame(), table_type="csv", encoding=encoding, sheet_name=None, sheet_names=[], warnings=["表格为空。"])
            except Exception as exc:
                last_error = str(exc)
                continue
        raise ValueError(f"我识别到你上传的是表格文件，但读取时发现编码不兼容。你可以尝试另存为 UTF-8 编码的 CSV，或上传 Excel 格式文件。{(' 原因：' + last_error) if last_error else ''}")

    engine = "openpyxl" if suffix == ".xlsx" else "xlrd"
    if suffix == ".xls":
        try:
            import xlrd  # noqa: F401
        except ModuleNotFoundError as exc:
            raise ValueError("当前环境缺少 xlrd，暂时无法读取 .xls 文件。你可以改存为 .xlsx 后重新上传。") from exc

    try:
        excel_file = pd.ExcelFile(path, engine=engine)
        sheet_names = list(excel_file.sheet_names or [])
        warnings_list: list[str] = []
        if not sheet_names:
            return TableLoadResult(df=pd.DataFrame(), table_type="excel", encoding=None, sheet_name=None, sheet_names=[], warnings=["Excel 文件中没有可读取的工作表。"])
        sheet_name = sheet_names[0]
        if len(sheet_names) > 1:
            warnings_list.append(f"检测到 {len(sheet_names)} 个 sheet，当前默认分析第一个：{sheet_name}")
        df = pd.read_excel(excel_file, sheet_name=sheet_name, nrows=PREVIEW_ROWS if preview_only else None)
        return TableLoadResult(df=df, table_type="excel", encoding=None, sheet_name=sheet_name, sheet_names=sheet_names, warnings=warnings_list)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Excel 文件读取失败，文件可能已损坏或格式不兼容。{exc}") from exc


class DataAnalysisSkill(BaseSkill):
    name = "data-analysis-skill"
    display_name = "表格数据分析"
    description = "用于读取和分析普通 CSV / Excel 表格数据，支持精确查询、分组统计、缺失值检查、基础统计、概览和清洗建议。"
    category = "数据技能"
    requires_file = True
    supported_file_types = sorted(TABLE_FILE_SUFFIXES)
    usage = "上传普通 CSV / Excel 表格后，可以做计数、筛选、分组统计、缺失值检查、基础统计和总结。"
    skill_mode = "executable"

    def __init__(self) -> None:
        self.planner = TableQueryPlanner()
        self.actions = [
            self._action("count_records", "统计满足条件的记录数量。"),
            self._action("groupby_count", "按字段统计每类数量。"),
            self._action("groupby_statistics", "按字段分组后做 sum/mean/max/min/median/count 聚合。"),
            self._action("query_table", "按条件筛选并返回前 N 条预览。"),
            self._action("sort_table", "按字段排序后返回结果。"),
            self._action("top_n", "返回指定字段排序后的前 N 条记录。"),
            self._action("missing_value_check", "检查缺失值。"),
            self._action("basic_statistics", "查看基础统计。"),
            self._action("visualize_table", "给出可视化建议。"),
            self._action("clean_table", "给出清洗建议。"),
            self._action("summarize_table", "总结表格概况。"),
            self._action("clarify", "当意图或字段不明确时追问。"),
            self._action("inspect_table", "读取表格 schema。"),
            self._action("chart_suggestion", "兼容旧动作：图表建议。"),
            self._action("categorical_summary", "兼容旧动作：类别频次。"),
            self._action("simple_query_table", "兼容旧动作：简单表格问答。"),
            self._action("export_clean_preview", "兼容旧动作：清洗预览。"),
        ]

    def _action(self, name: str, description: str) -> dict[str, Any]:
        return {
            "name": name,
            "display_name": name,
            "description": description,
            "enabled": True,
            "available": True,
            "status": "ready",
            "unavailable_reason": "",
        }

    def run(self, **kwargs: Any) -> SkillResult:
        requested_action = str(kwargs.get("action_name") or "summarize_table").strip() or "summarize_table"
        file_path = Path(str(kwargs.get("file_path") or "")).expanduser()
        message = str(kwargs.get("message") or kwargs.get("original_message") or "").strip()
        planner_payload = kwargs.get("table_query_plan")

        if not file_path.exists():
            return self._failure_result(requested_action, "我没有找到这个表格文件，请重新上传后再试一次。", "文件不存在。", filename="")

        try:
            load_result = load_table_file(file_path, preview_only=False)
        except ValueError as exc:
            return self._failure_result(requested_action, str(exc), str(exc), filename=file_path.name)
        except FileNotFoundError as exc:
            return self._failure_result(requested_action, "我没有找到这个表格文件，请重新上传后再试一次。", str(exc), filename=file_path.name)
        except Exception as exc:
            return self._failure_result(requested_action, "表格读取失败，请确认文件内容完整，或重新导出后再试一次。", str(exc), filename=file_path.name)

        df = load_result.df.copy()
        if df.empty and not list(df.columns):
            return self._empty_table_result(requested_action, load_result, file_path.name)

        metadata = self._build_metadata(df, load_result, file_path.name)
        plan = self._resolve_plan(requested_action, message, df, planner_payload)
        if plan.need_clarification:
            return self._clarify_result(plan, metadata)

        try:
            return self._execute_plan(plan, df, metadata)
        except Exception as exc:  # pragma: no cover
            return self._failure_result(plan.action, "执行表格分析时出现异常，请换个问法再试，或检查表格字段格式。", str(exc), filename=file_path.name)

    def _resolve_plan(
        self,
        requested_action: str,
        message: str,
        df: pd.DataFrame,
        planner_payload: Any,
    ) -> TableQueryPlan:
        if isinstance(planner_payload, TableQueryPlan):
            return planner_payload
        if isinstance(planner_payload, dict) and planner_payload.get("action"):
            filters = [TableFilter(**item) if not isinstance(item, TableFilter) else item for item in planner_payload.get("filters", [])]
            payload = dict(planner_payload)
            payload["filters"] = filters
            return TableQueryPlan(**payload)

        aliased_action = ACTION_ALIASES.get(requested_action, requested_action)
        if aliased_action in {"clarify", "summarize_table", "query_table", "count_records", "groupby_count", "groupby_statistics", "top_n", "sort_table"} and message:
            plan = self.planner.plan(message, df)
            if requested_action == "summarize_table" and plan.action == "summarize_table":
                return plan
            if requested_action in {"simple_query_table", "summarize_table"}:
                return plan
            if aliased_action in {"query_table", "count_records", "groupby_count", "groupby_statistics", "top_n", "sort_table"}:
                return plan if plan.action != "summarize_table" else TableQueryPlan(action=aliased_action, confidence=0.65, reason="按显式 action 执行")

        if aliased_action == "inspect_table":
            return TableQueryPlan(action="inspect_table", confidence=1.0, reason="显式读取表格结构")
        if aliased_action == "missing_value_check":
            target_column = self.planner._find_column_from_text(message, [str(column) for column in df.columns]) if message else None
            return TableQueryPlan(action="missing_value_check", confidence=0.95, target_column=target_column, reason="显式缺失值检查")
        if aliased_action == "basic_statistics":
            target_column = self.planner._find_column_from_text(message, [str(column) for column in df.columns]) if message else None
            return TableQueryPlan(action="basic_statistics", confidence=0.95, target_column=target_column, reason="显式基础统计")
        if aliased_action == "visualize_table":
            return TableQueryPlan(action="visualize_table", confidence=0.9, reason="显式图表建议")
        if aliased_action == "clean_table":
            return TableQueryPlan(action="clean_table", confidence=0.9, reason="显式清洗预览")
        if aliased_action == "groupby_count":
            categorical = self._categorical_columns(df)
            if categorical:
                return TableQueryPlan(action="groupby_count", confidence=0.75, group_by=categorical[0], limit=PREVIEW_ROWS, reason="兼容旧类别汇总动作")
            return self.planner.plan(message, df)
        return TableQueryPlan(action=aliased_action or "summarize_table", confidence=0.7, reason="按显式 action 执行")

    def _execute_plan(self, plan: TableQueryPlan, df: pd.DataFrame, metadata: dict[str, Any]) -> SkillResult:
        action = plan.action
        if action == "inspect_table":
            return self._inspect_table_result(metadata, plan)
        if action == "count_records":
            return self._count_records_result(df, metadata, plan)
        if action == "groupby_count":
            return self._groupby_count_result(df, metadata, plan)
        if action == "groupby_statistics":
            return self._groupby_statistics_result(df, metadata, plan)
        if action == "query_table":
            return self._query_table_result(df, metadata, plan)
        if action in {"top_n", "sort_table"}:
            return self._top_n_result(df, metadata, plan)
        if action == "missing_value_check":
            return self._missing_value_result(df, metadata, plan)
        if action == "basic_statistics":
            return self._basic_statistics_result(df, metadata, plan)
        if action == "visualize_table":
            return self._visualize_table_result(metadata, plan)
        if action == "clean_table":
            return self._clean_table_result(df, metadata, plan)
        return self._summarize_table_result(df, metadata, plan)

    def _build_metadata(self, df: pd.DataFrame, load_result: TableLoadResult, filename: str) -> dict[str, Any]:
        schema = build_table_schema(df)
        return {
            "filename": filename,
            "table_type": load_result.table_type,
            "rows": int(len(df)),
            "columns": int(len(df.columns)),
            "sheet_name": load_result.sheet_name,
            "sheet_names": list(load_result.sheet_names),
            "encoding": load_result.encoding,
            "column_names": [str(column) for column in df.columns],
            "numeric_columns": self._numeric_columns(df),
            "categorical_columns": self._categorical_columns(df),
            "datetime_columns": self._datetime_columns(df),
            "schema": schema,
            "warnings": list(load_result.warnings or []),
        }

    def _numeric_columns(self, df: pd.DataFrame) -> list[str]:
        return [str(column) for column in df.columns if is_numeric_dtype(df[column])]

    def _categorical_columns(self, df: pd.DataFrame) -> list[str]:
        numeric = set(self._numeric_columns(df))
        datetime_columns = set(self._datetime_columns(df))
        return [str(column) for column in df.columns if str(column) not in numeric and str(column) not in datetime_columns]

    def _datetime_columns(self, df: pd.DataFrame) -> list[str]:
        columns: list[str] = []
        for column in df.columns:
            series = df[column]
            if is_datetime64_any_dtype(series):
                columns.append(str(column))
                continue
            if is_numeric_dtype(series):
                continue
            sample = series.dropna().astype(str).head(10)
            if sample.empty:
                continue
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    parsed = pd.to_datetime(sample, errors="coerce")
            except Exception:
                continue
            if float(parsed.notna().mean()) >= 0.8:
                columns.append(str(column))
        return columns

    def _normalize_text_value(self, value: Any) -> str:
        text = str(value if value is not None else "").replace("\u3000", " ").strip()
        text = text.strip("\"'“”‘’")
        return normalize_filter_value(text)

    def _normalize_text_series(self, series: pd.Series) -> pd.Series:
        return series.fillna("").astype(str).map(self._normalize_text_value)

    def diagnose_zero_match(self, df: pd.DataFrame, selected_column: str, value: Any) -> dict[str, Any]:
        normalized_value = self._normalize_text_value(value)
        diagnosis = {
            "selected_column_top_values": [],
            "value_found_in_other_columns": [],
            "suggestion": "",
        }
        if selected_column in df.columns:
            normalized_series = self._normalize_text_series(df[selected_column])
            top_values = normalized_series[normalized_series != ""].value_counts().head(10)
            diagnosis["selected_column_top_values"] = [{"value": str(index), "count": int(count)} for index, count in top_values.items()]

        for column in df.columns:
            if str(column) == str(selected_column):
                continue
            normalized_series = self._normalize_text_series(df[column])
            count = int((normalized_series == normalized_value).sum())
            if count > 0:
                diagnosis["value_found_in_other_columns"].append({"column": str(column), "count": count})

        if diagnosis["value_found_in_other_columns"]:
            first = diagnosis["value_found_in_other_columns"][0]
            diagnosis["suggestion"] = f"{selected_column} 列中没有“{normalized_value}”，但 {first['column']} 列中存在“{normalized_value}”。你是否想按 {first['column']}={normalized_value} 筛选？"
        return diagnosis

    def _apply_filters_with_debug(self, df: pd.DataFrame, filters: list[TableFilter]) -> tuple[pd.DataFrame, dict[str, Any]]:
        filtered = df.copy()
        debug: dict[str, Any] = {"normalized_value": None, "exact_match_count": None, "contains_match_count": None, "used_contains_fallback": False}
        for rule in filters:
            if rule.column not in filtered.columns:
                raise KeyError(rule.column)
            series = filtered[rule.column]
            operator = rule.operator
            if operator == "is_null":
                mask = series.isna()
            elif operator == "not_null":
                mask = series.notna()
            elif operator in {"gt", "gte", "lt", "lte"}:
                numeric_series = pd.to_numeric(series, errors="coerce")
                target_value = float(rule.value)
                if operator == "gt":
                    mask = numeric_series > target_value
                elif operator == "gte":
                    mask = numeric_series >= target_value
                elif operator == "lt":
                    mask = numeric_series < target_value
                else:
                    mask = numeric_series <= target_value
            else:
                normalized_series = self._normalize_text_series(series)
                normalized_value = self._normalize_text_value(rule.value)
                debug["normalized_value"] = normalized_value
                if operator == "contains":
                    mask = normalized_series.str.contains(normalized_value, case=False, na=False)
                elif operator == "neq":
                    mask = normalized_series.str.casefold() != normalized_value.casefold()
                else:
                    exact_mask = normalized_series.str.casefold() == normalized_value.casefold()
                    debug["exact_match_count"] = int(exact_mask.sum())
                    if int(exact_mask.sum()) == 0 and normalized_value:
                        contains_mask = normalized_series.str.contains(re.escape(normalized_value), case=False, na=False, regex=True)
                        debug["contains_match_count"] = int(contains_mask.sum())
                        if int(contains_mask.sum()) > 0:
                            mask = contains_mask
                            debug["used_contains_fallback"] = True
                        else:
                            mask = exact_mask
                    else:
                        debug["contains_match_count"] = int(exact_mask.sum())
                        mask = exact_mask
            filtered = filtered.loc[mask]
        return filtered, debug

    def _apply_filters(self, df: pd.DataFrame, filters: list[TableFilter]) -> pd.DataFrame:
        filtered, _ = self._apply_filters_with_debug(df, filters)
        return filtered

    def _count_records_result(self, df: pd.DataFrame, metadata: dict[str, Any], plan: TableQueryPlan) -> SkillResult:
        filtered, filter_debug = self._apply_filters_with_debug(df, plan.filters)
        matched_count = int(len(filtered))
        total_count = int(len(df))
        ratio = matched_count / total_count if total_count else 0.0
        filter_text = self._filters_text(plan.filters)
        summary = f"{filter_text} 的记录共有 {matched_count} 条。"
        markdown = f"在该表格中，{filter_text} 的记录共有 **{matched_count}** 条；总记录数为 **{total_count}** 条，占比 **{ratio * 100:.2f}%**。"
        diagnosis = {}
        if matched_count == 0 and plan.filters:
            first_filter = plan.filters[0]
            diagnosis = self.diagnose_zero_match(df, first_filter.column, first_filter.value)
            if diagnosis.get("suggestion"):
                markdown += f"\n\n{diagnosis['suggestion']}"
            if diagnosis.get("selected_column_top_values"):
                top_values_text = "，".join(f"{item['value']}({item['count']})" for item in diagnosis["selected_column_top_values"][:10])
                markdown += f"\n\n`{first_filter.column}` 列当前高频值示例：{top_values_text}"
        data = {
            "matched_count": matched_count,
            "total_count": total_count,
            "ratio": ratio,
            "filters": [item.to_dict() for item in plan.filters],
            "preview": self._preview_records(filtered.head(min(PREVIEW_ROWS, matched_count))),
            "diagnosis": diagnosis,
            "metadata": metadata,
        }
        extra_debug = {
            "normalized_value": filter_debug.get("normalized_value"),
            "exact_match_count": filter_debug.get("exact_match_count"),
            "contains_match_count": filter_debug.get("contains_match_count"),
        }
        return self._success_result("count_records", summary, markdown, data, metadata, plan, extra_debug=extra_debug)

    def _groupby_count_result(self, df: pd.DataFrame, metadata: dict[str, Any], plan: TableQueryPlan) -> SkillResult:
        if not plan.group_by or plan.group_by not in df.columns:
            return self._clarify_result(
                TableQueryPlan(
                    action="clarify",
                    confidence=0.4,
                    need_clarification=True,
                    clarification_question="我没有定位到要分组统计的字段。你可以直接说“每个 province 有多少条？”",
                    reason="group_by 缺失",
                ),
                metadata,
            )
        counts = df[plan.group_by].fillna("(空值)").astype(str).value_counts(dropna=False)
        total = int(len(df))
        limit = int(plan.limit or PREVIEW_ROWS)
        rows = []
        for value, count in counts.head(limit).items():
            rows.append({"value": str(value), "count": int(count), "ratio": round(int(count) / total, 4) if total else 0.0})
        markdown = self._markdown_table(["类别", "数量", "占比"], [[row["value"], row["count"], f'{row["ratio"] * 100:.2f}%'] for row in rows])
        if len(counts) > limit:
            markdown += f"\n\n已按数量展示前 **{limit}** 类，其余类别已省略。"
        summary = f"已按 `{plan.group_by}` 统计数量，共识别 {len(counts)} 个类别。"
        data = {
            "group_by": plan.group_by,
            "rows": rows,
            "total_count": total,
            "truncated": len(counts) > limit,
            "metadata": metadata,
        }
        return self._success_result("groupby_count", summary, markdown, data, metadata, plan)

    def _groupby_statistics_result(self, df: pd.DataFrame, metadata: dict[str, Any], plan: TableQueryPlan) -> SkillResult:
        if not plan.group_by or plan.group_by not in df.columns:
            return self._clarify_result(TableQueryPlan(action="clarify", confidence=0.4, need_clarification=True, clarification_question="没有定位到分组字段，请告诉我按哪一列统计。", reason="缺少分组字段"), metadata)
        if not plan.target_column or plan.target_column not in df.columns:
            return self._clarify_result(TableQueryPlan(action="clarify", confidence=0.4, need_clarification=True, clarification_question="没有定位到聚合目标列，请告诉我要统计哪个字段。", reason="缺少目标字段"), metadata)

        agg = str(plan.agg or "sum")
        working = df[[plan.group_by, plan.target_column]].copy()
        if agg != "count":
            working[plan.target_column] = pd.to_numeric(working[plan.target_column], errors="coerce")
        grouped = working.groupby(plan.group_by, dropna=False)[plan.target_column].agg(agg)
        rows = []
        for key, value in grouped.head(int(plan.limit or PREVIEW_ROWS)).items():
            rendered = None if pd.isna(value) else round(float(value), 4) if isinstance(value, (int, float)) else value
            rows.append({"group": "(空值)" if pd.isna(key) else str(key), "value": rendered})
        markdown = self._markdown_table(["分组", f"{plan.target_column}.{agg}"], [[row["group"], row["value"]] for row in rows])
        summary = f"已按 `{plan.group_by}` 对 `{plan.target_column}` 做 `{agg}` 聚合。"
        data = {
            "group_by": plan.group_by,
            "target_column": plan.target_column,
            "agg": agg,
            "rows": rows,
            "metadata": metadata,
        }
        return self._success_result("groupby_statistics", summary, markdown, data, metadata, plan)

    def _query_table_result(self, df: pd.DataFrame, metadata: dict[str, Any], plan: TableQueryPlan) -> SkillResult:
        filtered, filter_debug = self._apply_filters_with_debug(df, plan.filters)
        limit = int(plan.limit or PREVIEW_ROWS)
        preview_df = filtered.head(limit)
        preview = self._preview_records(preview_df)
        markdown = f"匹配记录共 **{len(filtered)}** 条，下面展示前 **{min(limit, len(filtered))}** 条：\n\n"
        diagnosis = {}
        if preview:
            markdown += self._markdown_table(list(preview_df.columns), [list(row.values()) for row in preview])
        else:
            markdown += "没有匹配到记录。"
            if plan.filters:
                first_filter = plan.filters[0]
                diagnosis = self.diagnose_zero_match(df, first_filter.column, first_filter.value)
                if diagnosis.get("suggestion"):
                    markdown += f"\n\n{diagnosis['suggestion']}"
                if diagnosis.get("selected_column_top_values"):
                    top_values_text = "，".join(f"{item['value']}({item['count']})" for item in diagnosis["selected_column_top_values"][:10])
                    markdown += f"\n\n`{first_filter.column}` 列当前高频值示例：{top_values_text}"
        summary = f"已筛选出 {len(filtered)} 条记录，并返回前 {min(limit, len(filtered))} 条预览。"
        data = {
            "matched_count": int(len(filtered)),
            "total_count": int(len(df)),
            "columns": [str(column) for column in preview_df.columns],
            "filters": [item.to_dict() for item in plan.filters],
            "limit": limit,
            "preview": preview,
            "diagnosis": diagnosis,
            "metadata": metadata,
        }
        extra_debug = {
            "normalized_value": filter_debug.get("normalized_value"),
            "exact_match_count": filter_debug.get("exact_match_count"),
            "contains_match_count": filter_debug.get("contains_match_count"),
        }
        return self._success_result("query_table", summary, markdown, data, metadata, plan, extra_debug=extra_debug)

    def _top_n_result(self, df: pd.DataFrame, metadata: dict[str, Any], plan: TableQueryPlan) -> SkillResult:
        if not plan.sort_by or plan.sort_by not in df.columns:
            return self._clarify_result(TableQueryPlan(action="clarify", confidence=0.4, need_clarification=True, clarification_question="没有定位到排序列，请告诉我按哪个字段排序。", reason="缺少排序字段"), metadata)
        limit = int(plan.limit or PREVIEW_ROWS)
        sort_order = str(plan.sort_order or "desc").lower()
        working = df.copy()
        numeric_series = pd.to_numeric(working[plan.sort_by], errors="coerce")
        if numeric_series.notna().any():
            working = working.assign(**{plan.sort_by: numeric_series})
        sorted_df = working.sort_values(by=plan.sort_by, ascending=sort_order == "asc", na_position="last")
        preview_df = sorted_df.head(limit)
        preview = self._preview_records(preview_df)
        markdown = self._markdown_table(list(preview_df.columns), [list(row.values()) for row in preview]) if preview else "没有可展示的结果。"
        summary = f"已按 `{plan.sort_by}` {'升序' if sort_order == 'asc' else '降序'} 排序，并返回前 {len(preview)} 条。"
        data = {
            "sort_by": plan.sort_by,
            "sort_order": sort_order,
            "limit": limit,
            "preview": preview,
            "metadata": metadata,
        }
        return self._success_result(plan.action, summary, markdown, data, metadata, plan)

    def _missing_value_result(self, df: pd.DataFrame, metadata: dict[str, Any], plan: TableQueryPlan) -> SkillResult:
        if plan.target_column:
            if plan.target_column not in df.columns:
                return self._clarify_result(TableQueryPlan(action="clarify", confidence=0.4, need_clarification=True, clarification_question=f"没有找到 {plan.target_column} 列。", reason="缺少目标列"), metadata)
            missing_count = int(df[plan.target_column].isna().sum())
            total_count = int(len(df))
            markdown = f"`{plan.target_column}` 这一列共有 **{missing_count}** 个空值；总行数为 **{total_count}**。"
            summary = f"`{plan.target_column}` 的空值数量为 {missing_count}。"
            data = {"target_column": plan.target_column, "missing_count": missing_count, "total_count": total_count, "metadata": metadata}
            return self._success_result("missing_value_check", summary, markdown, data, metadata, plan)

        rows = []
        for column in df.columns:
            missing_count = int(df[column].isna().sum())
            if missing_count > 0:
                rows.append({"column": str(column), "missing_count": missing_count, "ratio": round(missing_count / len(df), 4) if len(df) else 0.0})
        markdown = self._markdown_table(["列名", "空值数", "占比"], [[row["column"], row["missing_count"], f'{row["ratio"] * 100:.2f}%'] for row in rows]) if rows else "当前表格没有检测到缺失值。"
        summary = "已完成全表缺失值检查。"
        data = {"columns": rows, "metadata": metadata}
        return self._success_result("missing_value_check", summary, markdown, data, metadata, plan)

    def _basic_statistics_result(self, df: pd.DataFrame, metadata: dict[str, Any], plan: TableQueryPlan) -> SkillResult:
        if plan.target_column:
            if plan.target_column not in df.columns:
                return self._clarify_result(TableQueryPlan(action="clarify", confidence=0.4, need_clarification=True, clarification_question=f"没有找到 {plan.target_column} 列。", reason="缺少目标列"), metadata)
            series = pd.to_numeric(df[plan.target_column], errors="coerce").dropna()
            if series.empty:
                return self._clarify_result(TableQueryPlan(action="clarify", confidence=0.4, need_clarification=True, clarification_question=f"`{plan.target_column}` 不是可统计的数值列。", reason="目标列非数值"), metadata)
            stats = self._series_stats(series)
            markdown = self._markdown_table(["指标", "值"], [[key, value] for key, value in stats.items()])
            summary = f"已完成 `{plan.target_column}` 的基础统计。"
            data = {"target_column": plan.target_column, "statistics": stats, "metadata": metadata}
            return self._success_result("basic_statistics", summary, markdown, data, metadata, plan)

        rows = []
        for column in self._numeric_columns(df):
            series = pd.to_numeric(df[column], errors="coerce").dropna()
            if not series.empty:
                stats = self._series_stats(series)
                rows.append({"column": column, **stats})
        markdown = self._markdown_table(
            ["列名", "count", "mean", "min", "median", "max"],
            [[row["column"], row["count"], row["mean"], row["min"], row["median"], row["max"]] for row in rows],
        ) if rows else "当前表格没有可用于统计的数值列。"
        summary = f"已完成全表基础统计，共覆盖 {len(rows)} 个数值列。"
        data = {"rows": rows, "metadata": metadata}
        return self._success_result("basic_statistics", summary, markdown, data, metadata, plan)

    def _visualize_table_result(self, metadata: dict[str, Any], plan: TableQueryPlan) -> SkillResult:
        numeric_columns = metadata.get("numeric_columns") or []
        categorical_columns = metadata.get("categorical_columns") or []
        datetime_columns = metadata.get("datetime_columns") or []
        suggestions: list[str] = []
        if plan.group_by:
            suggestions.append(f"如果重点是 `{plan.group_by}` 的分布，优先做柱状图。")
        if plan.target_column and datetime_columns:
            suggestions.append(f"如果要看 `{plan.target_column}` 随时间变化，优先做折线图。")
        if numeric_columns and categorical_columns:
            suggestions.append(f"类别列 `{categorical_columns[0]}` 和数值列 `{numeric_columns[0]}` 适合做分组柱状图。")
        if len(numeric_columns) >= 2:
            suggestions.append(f"`{numeric_columns[0]}` 和 `{numeric_columns[1]}` 可以做散点图。")
        if not suggestions:
            suggestions.append("当前数据更适合先做表格概览，再决定图表类型。")
        markdown = "\n".join(f"- {item}" for item in suggestions)
        summary = "已根据当前表格结构给出可视化建议。"
        data = {"suggestions": suggestions, "chart_type": plan.chart_type, "metadata": metadata}
        return self._success_result("visualize_table", summary, markdown, data, metadata, plan)

    def _clean_table_result(self, df: pd.DataFrame, metadata: dict[str, Any], plan: TableQueryPlan) -> SkillResult:
        duplicate_rows = int(df.duplicated().sum())
        missing_total = int(df.isna().sum().sum())
        empty_columns = [str(column) for column in df.columns if int(df[column].isna().sum()) == len(df) and len(df) > 0]
        suggestions = []
        if duplicate_rows > 0:
            suggestions.append(f"检测到 **{duplicate_rows}** 行重复记录，可以按业务主键去重。")
        if missing_total > 0:
            suggestions.append(f"检测到 **{missing_total}** 个缺失单元格，建议先区分可删除和需填充字段。")
        if empty_columns:
            suggestions.append(f"这些列全为空：`{'`、`'.join(empty_columns)}`，可优先删除。")
        if not suggestions:
            suggestions.append("当前表格结构比较整齐，可以直接继续分析。")
        markdown = "\n".join(f"- {item}" for item in suggestions)
        summary = "已生成表格清洗建议。"
        data = {"duplicate_rows": duplicate_rows, "missing_total": missing_total, "empty_columns": empty_columns, "suggestions": suggestions, "metadata": metadata}
        return self._success_result("clean_table", summary, markdown, data, metadata, plan)

    def _summarize_table_result(self, df: pd.DataFrame, metadata: dict[str, Any], plan: TableQueryPlan) -> SkillResult:
        schema = metadata["schema"]
        numeric_columns = metadata.get("numeric_columns") or []
        categorical_columns = metadata.get("categorical_columns") or []
        warnings_list = metadata.get("warnings") or []
        markdown_lines = [
            f"该表格共有 **{metadata['rows']}** 行、**{metadata['columns']}** 列。",
            f"主要字段包括：{('、'.join(metadata['column_names'][:8]) if metadata['column_names'] else '暂未识别')}",
            f"数值列：{('、'.join(numeric_columns) if numeric_columns else '无')}",
            f"类别列：{('、'.join(categorical_columns[:8]) if categorical_columns else '无')}",
        ]
        if warnings_list:
            markdown_lines.append("提醒：")
            markdown_lines.extend(f"- {item}" for item in warnings_list)
        summary = f"已完成 `{metadata['filename']}` 的表格概览分析。"
        data = {"metadata": metadata, "schema": schema}
        return self._success_result("summarize_table", summary, "\n\n".join(markdown_lines), data, metadata, plan)

    def _inspect_table_result(self, metadata: dict[str, Any], plan: TableQueryPlan) -> SkillResult:
        schema = metadata["schema"]
        rows = [
            [item["name"], item["dtype"], item["null_count"], " / ".join(item["sample_values"][:3])]
            for item in schema["columns"]
        ]
        markdown = self._markdown_table(["列名", "类型", "空值数", "样例值"], rows) if rows else "当前没有识别到有效字段。"
        summary = f"已读取 `{metadata['filename']}` 的表格 schema。"
        data = {"metadata": metadata, "schema": schema}
        return self._success_result("inspect_table", summary, markdown, data, metadata, plan)

    def _clarify_result(self, plan: TableQueryPlan, metadata: dict[str, Any]) -> SkillResult:
        question = str(plan.clarification_question or "需要进一步确认你的表格分析目标。")
        payload = {
            "success": False,
            "skill_name": self.name,
            "action": "clarify",
            "summary": "需要进一步确认",
            "markdown": question,
            "analysis_markdown": question,
            "need_clarification": True,
            "clarification_question": question,
            "metadata": metadata,
            "artifacts": [],
            "debug": {
                "planner_confidence": plan.confidence,
                "planner_reason": plan.reason,
                "route": "table_analysis",
            },
            "tool_info": self._tool_info("clarify", metadata, success=False, error=question),
        }
        return SkillResult(
            success=False,
            skill_name=self.name,
            action_name="clarify",
            summary="需要进一步确认",
            data=payload,
            errors=[],
        )

    def _success_result(
        self,
        action: str,
        summary: str,
        markdown: str,
        data: dict[str, Any],
        metadata: dict[str, Any],
        plan: TableQueryPlan,
        extra_debug: dict[str, Any] | None = None,
    ) -> SkillResult:
        debug_payload = {
            "planner_confidence": plan.confidence,
            "planner_reason": plan.reason,
            "route": "table_analysis",
        }
        if extra_debug:
            debug_payload.update({key: value for key, value in extra_debug.items() if value is not None})
        payload = {
            "success": True,
            "skill_name": self.name,
            "action": action,
            "summary": summary,
            "markdown": markdown,
            "analysis_markdown": markdown,
            "data": data,
            "metadata": metadata,
            "artifacts": [],
            "debug": debug_payload,
            "tool_info": self._tool_info(action, metadata, success=True, error=""),
        }
        if action == "basic_statistics":
            rows = list((data or {}).get("rows") or [])
            payload["statistics"] = {
                "numeric_summary": {
                    row["column"]: {
                        "count": row["count"],
                        "mean": row["mean"],
                        "min": row["min"],
                        "median": row["median"],
                        "max": row["max"],
                    }
                    for row in rows
                    if row.get("column")
                },
                "categorical_summary": {},
            }
            payload["quality"] = {"missing_cells": 0}
        if action == "visualize_table":
            payload["statistics"] = {"chart_suggestions": list((data or {}).get("suggestions") or [])}
        if action == "missing_value_check":
            if data.get("missing_count") is not None:
                payload["quality"] = {"missing_cells": int(data.get("missing_count") or 0)}
            elif data.get("columns") is not None:
                payload["quality"] = {"missing_cells": int(sum(int(item.get("missing_count") or 0) for item in data.get("columns") or []))}
        return SkillResult(
            success=True,
            skill_name=self.name,
            action_name=action,
            summary=summary,
            data=payload,
            errors=[],
        )

    def _tool_info(self, action_name: str, metadata: dict[str, Any], success: bool, error: str) -> dict[str, Any]:
        return {
            "source": "skill_execution",
            "skill": self.name,
            "action": action_name,
            "filename": metadata.get("filename", ""),
            "rows": metadata.get("rows", ""),
            "columns": metadata.get("columns", ""),
            "sheet_name": metadata.get("sheet_name", ""),
            "success": bool(success),
            "error": error or "",
            "mode": "data_analysis",
        }

    def _failure_result(self, action_name: str, message: str, error: str, filename: str) -> SkillResult:
        payload = {
            "success": False,
            "skill_name": self.name,
            "action": action_name,
            "summary": message,
            "markdown": message,
            "analysis_markdown": message,
            "error": message,
            "artifacts": [],
            "debug": {"planner_confidence": 0.0, "planner_reason": error, "route": "table_analysis"},
            "tool_info": {
                "source": "skill_execution",
                "skill": self.name,
                "action": action_name,
                "filename": filename,
                "rows": "",
                "columns": "",
                "sheet_name": "",
                "success": False,
                "error": message,
                "mode": "data_analysis",
            },
        }
        return SkillResult(success=False, skill_name=self.name, action_name=action_name, summary=message, data=payload, errors=[error])

    def _empty_table_result(self, action_name: str, load_result: TableLoadResult, filename: str) -> SkillResult:
        message = "我识别到你上传的是表格文件，但当前表格为空，暂时没有可分析的数据内容。"
        payload = {
            "success": False,
            "skill_name": self.name,
            "action": action_name,
            "summary": message,
            "markdown": message,
            "analysis_markdown": message,
            "metadata": {
                "filename": filename,
                "table_type": load_result.table_type,
                "rows": 0,
                "columns": 0,
                "sheet_name": load_result.sheet_name,
                "encoding": load_result.encoding,
                "column_names": [],
                "numeric_columns": [],
                "categorical_columns": [],
                "datetime_columns": [],
                "warnings": list(load_result.warnings or ["表格为空。"]),
                "schema": {"row_count": 0, "column_count": 0, "columns": []},
            },
            "quality": {"warnings": list(load_result.warnings or ["表格为空。"])},
            "artifacts": [],
            "debug": {"planner_confidence": 0.0, "planner_reason": "empty_table", "route": "table_analysis"},
            "tool_info": {
                "source": "skill_execution",
                "skill": self.name,
                "action": action_name,
                "filename": filename,
                "rows": 0,
                "columns": 0,
                "sheet_name": load_result.sheet_name or "",
                "success": False,
                "error": message,
                "mode": "data_analysis",
            },
        }
        return SkillResult(success=False, skill_name=self.name, action_name=action_name, summary=message, data=payload, errors=["empty_table"])

    def _preview_records(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        if df.empty:
            return []
        preview = df.fillna("").astype(object).to_dict(orient="records")
        rows: list[dict[str, Any]] = []
        for row in preview:
            rendered = {}
            for key, value in row.items():
                if isinstance(value, float) and math.isnan(value):
                    rendered[str(key)] = ""
                else:
                    rendered[str(key)] = value
            rows.append(rendered)
        return rows

    def _filters_text(self, filters: list[TableFilter]) -> str:
        if not filters:
            return "全部记录"
        parts = []
        for item in filters:
            if item.operator == "is_null":
                parts.append(f"{item.column} 为空")
            elif item.operator == "not_null":
                parts.append(f"{item.column} 不为空")
            else:
                op_map = {"eq": "等于", "neq": "不等于", "contains": "包含", "gt": "大于", "gte": "大于等于", "lt": "小于", "lte": "小于等于"}
                parts.append(f"{item.column} {op_map.get(item.operator, item.operator)} “{item.value}”")
        return " 且 ".join(parts)

    def _series_stats(self, series: pd.Series) -> dict[str, Any]:
        return {
            "count": int(series.count()),
            "mean": round(float(series.mean()), 4),
            "min": round(float(series.min()), 4),
            "median": round(float(series.median()), 4),
            "max": round(float(series.max()), 4),
        }

    def _markdown_table(self, headers: list[Any], rows: list[list[Any]]) -> str:
        if not headers:
            return ""
        header_line = "| " + " | ".join(str(item) for item in headers) + " |"
        divider_line = "| " + " | ".join("---" for _ in headers) + " |"
        body_lines = ["| " + " | ".join(str("" if value is None else value) for value in row) + " |" for row in rows]
        return "\n".join([header_line, divider_line, *body_lines])
