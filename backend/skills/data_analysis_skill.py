from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import warnings

import pandas as pd
from pandas.api.types import is_datetime64_any_dtype, is_numeric_dtype

from .base import BaseSkill, SkillResult


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


@dataclass
class TableLoadResult:
    df: pd.DataFrame
    table_type: str
    encoding: str | None
    sheet_name: str | None
    sheet_names: list[str]
    warnings: list[str]


def infer_data_analysis_action(message: str, default_action: str = "summarize_table") -> str:
    normalized = str(message or "").strip().lower()
    if any(keyword in normalized for keyword in ("缺失值", "空值", "空列", "重复值", "重复行", "数据质量")):
        return "missing_value_check"
    if any(keyword in normalized for keyword in ("平均值", "最大值", "最小值", "标准差", "中位数", "统计")):
        return "basic_statistics"
    if any(keyword in normalized for keyword in ("每类", "分类统计", "频次", "类别")):
        return "categorical_summary"
    if any(keyword in normalized for keyword in ("适合画什么图", "画图", "可视化", "图表建议")):
        return "chart_suggestion"
    if any(keyword in normalized for keyword in ("清洗", "清理", "导出预览", "预览")):
        return "export_clean_preview"
    if any(keyword in normalized for keyword in ("字段", "列名", "结构", "行数", "列数", "inspect")):
        return "inspect_table"
    if any(
        keyword in normalized
        for keyword in (
            "主要记录",
            "记录什么",
            "记录的是",
            "主要讲什么",
            "主要内容",
            "内容是什么",
            "讲什么",
            "这份表主要",
            "这个文件主要",
            "这个表主要",
        )
    ):
        return "simple_query_table"
    if ("?" in normalized or "？" in normalized) and any(
        keyword in normalized for keyword in ("文件", "表格", "表", "数据", "csv", "excel")
    ) and any(keyword in normalized for keyword in ("什么", "内容", "记录", "说明", "用途", "讲", "是啥", "是什么")):
        return "simple_query_table"
    if any(keyword in normalized for keyword in ("总结", "主要讲什么", "主要内容", "表格内容")):
        return "summarize_table"
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
    except Exception as exc:  # pragma: no cover - defensive fallback
        return {"is_raman": False, "reason": f"preview_failed:{type(exc).__name__}", "matched_hints": []}

    df = load_result.df
    column_names = [_normalize_name(column) for column in df.columns]
    preview_text = " ".join(_normalize_name(value) for row in df.head(5).fillna("").astype(str).values.tolist() for value in row)
    matched_hints = sorted({hint for hint in RAMAN_TABLE_HINTS if hint in " ".join(column_names) or hint in preview_text})
    shift_like = any(token in " ".join(column_names) for token in ("shift", "wavenumber", "cm-1", "cm^-1", "波数"))
    intensity_like = any(token in " ".join(column_names) for token in ("intensity", "强度", "absorbance"))
    is_raman = (shift_like and intensity_like) or len(matched_hints) >= 2
    reason = "raman_column_hints" if is_raman else "no_raman_signal"
    return {
        "is_raman": bool(is_raman),
        "reason": reason,
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
        warnings: list[str] = []
        if not sheet_names:
            return TableLoadResult(df=pd.DataFrame(), table_type="excel", encoding=None, sheet_name=None, sheet_names=[], warnings=["Excel 文件中没有可读取的工作表。"])
        sheet_name = sheet_names[0]
        if len(sheet_names) > 1:
            warnings.append(f"检测到 {len(sheet_names)} 个 sheet，当前默认分析第一个：{sheet_name}")
        try:
            df = pd.read_excel(excel_file, sheet_name=sheet_name, nrows=PREVIEW_ROWS if preview_only else None)
        except Exception as exc:
            warnings.append(f"默认 sheet {sheet_name} 读取失败：{exc}")
            df = pd.DataFrame()
        return TableLoadResult(df=df, table_type="excel", encoding=None, sheet_name=sheet_name, sheet_names=sheet_names, warnings=warnings)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Excel 文件读取失败，文件可能已损坏或格式不兼容。{exc}") from exc


class DataAnalysisSkill(BaseSkill):
    name = "data-analysis-skill"
    display_name = "表格数据分析"
    description = "用于读取和分析普通 CSV / Excel 表格数据，支持字段识别、数据预览、缺失值检查、基础统计、简单图表建议和自然语言问答。"
    category = "数据技能"
    requires_file = True
    supported_file_types = sorted(TABLE_FILE_SUFFIXES)
    usage = "上传普通 CSV / Excel 表格后，可以做字段识别、缺失值检查、统计摘要和图表建议。"
    skill_mode = "executable"

    def __init__(self) -> None:
        self.actions = [
            self._action("inspect_table", "读取表格，识别字段、行数、列数、数据类型。"),
            self._action("summarize_table", "总结表格内容，包括主要字段、数据规模、可能含义。"),
            self._action("missing_value_check", "检查缺失值、空列、重复行。"),
            self._action("basic_statistics", "对数值列做均值、最大值、最小值、标准差、中位数等基础统计。"),
            self._action("categorical_summary", "对类别列做频次统计。"),
            self._action("chart_suggestion", "根据字段类型建议适合的图表。"),
            self._action("simple_query_table", "根据用户问题回答表格相关问题。"),
            self._action("export_clean_preview", "输出清洗建议或预览。"),
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
        action_name = str(kwargs.get("action_name") or "summarize_table")
        file_path = Path(str(kwargs.get("file_path") or "")).expanduser()
        message = str(kwargs.get("message") or kwargs.get("original_message") or "").strip()

        if not file_path.exists():
            return self._failure_result(action_name, "我没有找到这个表格文件，请重新上传后再试一次。", "文件不存在。", filename="")

        try:
            load_result = load_table_file(file_path, preview_only=False)
        except ValueError as exc:
            return self._failure_result(action_name, str(exc), str(exc), filename=file_path.name)
        except FileNotFoundError as exc:
            return self._failure_result(action_name, "我没有找到这个表格文件，请重新上传后再试一次。", str(exc), filename=file_path.name)
        except Exception as exc:
            return self._failure_result(action_name, "表格读取失败，请确认文件内容完整，或重新导出后再试一次。", str(exc), filename=file_path.name)

        df = load_result.df.copy()
        action_name = self._resolve_action(action_name, message)
        if df.empty and not list(df.columns):
            return self._empty_table_result(action_name, load_result, file_path.name)

        profile = self._profile_table(df, load_result, file_path.name)
        analysis_markdown = self._build_analysis_markdown(profile, action_name, message)
        summary = self._build_summary(profile, action_name, message)
        next_steps = self._build_next_steps(profile)
        data = {
            "skill": self.name,
            "action": action_name,
            "table_type": load_result.table_type,
            "summary": summary,
            "analysis_markdown": analysis_markdown,
            "metadata": profile["metadata"],
            "quality": profile["quality"],
            "statistics": profile["statistics"],
            "preview_rows": profile["preview_rows"],
            "next_steps": next_steps,
            "tool_info": self._tool_info(action_name, profile, success=True, error=""),
        }
        return SkillResult(
            success=True,
            skill_name=self.name,
            action_name=action_name,
            summary=summary,
            data=data,
            errors=[],
        )

    def _resolve_action(self, action_name: str, message: str) -> str:
        if action_name and action_name != "simple_query_table":
            return action_name
        return infer_data_analysis_action(message, default_action="simple_query_table")

    def _profile_table(self, df: pd.DataFrame, load_result: TableLoadResult, filename: str) -> dict[str, Any]:
        normalized_df = df.copy()
        normalized_df.columns = [str(column) if str(column).strip() else f"未命名列_{index + 1}" for index, column in enumerate(normalized_df.columns)]
        row_count = int(len(normalized_df))
        column_names = [str(column) for column in normalized_df.columns]
        datetime_columns = self._detect_datetime_columns(normalized_df)
        numeric_columns = [column for column in column_names if is_numeric_dtype(normalized_df[column])]
        categorical_columns = [column for column in column_names if column not in numeric_columns and column not in datetime_columns]

        field_rows: list[dict[str, Any]] = []
        empty_columns: list[str] = []
        duplicate_columns = self._detect_duplicate_columns(column_names)
        for column in column_names:
            series = normalized_df[column]
            missing_count = int(series.isna().sum())
            if missing_count >= row_count and row_count > 0:
                empty_columns.append(column)
            sample_value = ""
            non_null = series.dropna()
            if not non_null.empty:
                sample_value = str(non_null.iloc[0])[:48]
            field_rows.append(
                {
                    "name": column,
                    "type": self._friendly_dtype(column, normalized_df[column], datetime_columns),
                    "missing": missing_count,
                    "example": sample_value,
                }
            )

        numeric_summary = self._numeric_summary(normalized_df, numeric_columns)
        categorical_summary = self._categorical_summary(normalized_df, categorical_columns)
        preview_rows = normalized_df.head(PREVIEW_ROWS).fillna("").astype(str).to_dict(orient="records")
        missing_cells = int(normalized_df.isna().sum().sum())
        duplicate_rows = int(normalized_df.duplicated().sum()) if row_count else 0
        warnings = list(load_result.warnings or [])
        if duplicate_columns:
            warnings.append(f"检测到列名可能重复：{'、'.join(duplicate_columns)}")
        if not numeric_columns:
            warnings.append("当前没有明显的数值列，基础统计会比较有限。")
        if row_count > PREVIEW_ROWS:
            warnings.append(f"文件较大，界面回复只展示前 {PREVIEW_ROWS} 行摘要。")
        if any(str(name).lower().startswith("unnamed") for name in column_names):
            warnings.append("检测到未命名列，建议确认原始表头是否完整。")

        metadata = {
            "filename": filename,
            "table_type": load_result.table_type,
            "rows": row_count,
            "columns": int(len(column_names)),
            "sheet_name": load_result.sheet_name,
            "sheet_names": list(load_result.sheet_names),
            "encoding": load_result.encoding,
            "column_names": column_names,
            "numeric_columns": numeric_columns,
            "categorical_columns": categorical_columns,
            "datetime_columns": datetime_columns,
        }
        quality = {
            "missing_cells": missing_cells,
            "duplicate_rows": duplicate_rows,
            "empty_columns": empty_columns,
            "warnings": warnings,
        }
        statistics = {
            "numeric_summary": numeric_summary,
            "categorical_summary": categorical_summary,
            "chart_suggestions": self._chart_suggestions(metadata),
        }
        return {
            "metadata": metadata,
            "quality": quality,
            "statistics": statistics,
            "preview_rows": preview_rows,
            "field_rows": field_rows,
        }

    def _detect_datetime_columns(self, df: pd.DataFrame) -> list[str]:
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

    def _friendly_dtype(self, column: str, series: pd.Series, datetime_columns: list[str]) -> str:
        if column in datetime_columns:
            return "datetime"
        if is_numeric_dtype(series):
            return "numeric"
        return "categorical"

    def _detect_duplicate_columns(self, column_names: list[str]) -> list[str]:
        seen: dict[str, int] = {}
        duplicates: list[str] = []
        for name in column_names:
            base = str(name).split(".")[0]
            seen[base] = seen.get(base, 0) + 1
            if seen[base] == 2:
                duplicates.append(base)
        return duplicates

    def _numeric_summary(self, df: pd.DataFrame, numeric_columns: list[str]) -> dict[str, dict[str, float]]:
        summary: dict[str, dict[str, float]] = {}
        for column in numeric_columns[:12]:
            series = pd.to_numeric(df[column], errors="coerce").dropna()
            if series.empty:
                continue
            summary[column] = {
                "mean": round(float(series.mean()), 4),
                "std": round(float(series.std(ddof=1)) if len(series) > 1 else 0.0, 4),
                "min": round(float(series.min()), 4),
                "median": round(float(series.median()), 4),
                "max": round(float(series.max()), 4),
            }
        return summary

    def _categorical_summary(self, df: pd.DataFrame, categorical_columns: list[str]) -> dict[str, list[dict[str, Any]]]:
        summary: dict[str, list[dict[str, Any]]] = {}
        for column in categorical_columns[:8]:
            series = df[column].dropna().astype(str)
            if series.empty:
                continue
            top_items = series.value_counts().head(5)
            summary[column] = [{"value": str(index), "count": int(count)} for index, count in top_items.items()]
        return summary

    def _chart_suggestions(self, metadata: dict[str, Any]) -> list[str]:
        numeric_columns = list(metadata.get("numeric_columns") or [])
        categorical_columns = list(metadata.get("categorical_columns") or [])
        datetime_columns = list(metadata.get("datetime_columns") or [])
        suggestions: list[str] = []
        if len(categorical_columns) == 1 and not numeric_columns:
            suggestions.append(f"`{categorical_columns[0]}` 适合做柱状图或饼图。")
        if len(numeric_columns) == 1:
            suggestions.append(f"`{numeric_columns[0]}` 适合做直方图或箱线图。")
        if datetime_columns and numeric_columns:
            suggestions.append(f"`{datetime_columns[0]}` 搭配 `{numeric_columns[0]}` 适合做折线图。")
        if len(numeric_columns) >= 2:
            suggestions.append(f"`{numeric_columns[0]}` 和 `{numeric_columns[1]}` 适合做散点图。")
        if categorical_columns and numeric_columns:
            suggestions.append(f"`{categorical_columns[0]}` 搭配 `{numeric_columns[0]}` 适合做分组柱状图或箱线图。")
        if len(numeric_columns) >= 3:
            suggestions.append("多个数值列可以进一步做相关性热图。")
        if not suggestions:
            suggestions.append("当前字段类型比较混合，建议先补充字段含义后再决定图表。")
        return suggestions

    def _build_field_table(self, field_rows: list[dict[str, Any]]) -> str:
        lines = ["| 字段名 | 类型 | 缺失值数量 | 示例值 |", "| --- | --- | ---: | --- |"]
        for item in field_rows[:20]:
            lines.append(f"| {item['name']} | {item['type']} | {item['missing']} | {item['example']} |")
        return "\n".join(lines)

    def _build_numeric_table(self, numeric_summary: dict[str, dict[str, float]]) -> str:
        if not numeric_summary:
            return "当前没有可展示的数值列基础统计。"
        lines = ["| 字段名 | 均值 | 标准差 | 最小值 | 中位数 | 最大值 |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
        for column, stats in numeric_summary.items():
            lines.append(
                f"| {column} | {stats['mean']} | {stats['std']} | {stats['min']} | {stats['median']} | {stats['max']} |"
            )
        return "\n".join(lines)

    def _build_categorical_text(self, categorical_summary: dict[str, list[dict[str, Any]]]) -> str:
        if not categorical_summary:
            return "当前没有明显的类别列，或类别列样本过少。"
        lines: list[str] = []
        for column, items in categorical_summary.items():
            joined = "；".join(f"{entry['value']} ({entry['count']})" for entry in items)
            lines.append(f"- `{column}`：{joined}")
        return "\n".join(lines)

    def _build_clean_preview(self, profile: dict[str, Any]) -> list[str]:
        quality = profile["quality"]
        metadata = profile["metadata"]
        suggestions: list[str] = []
        if quality["missing_cells"] > 0:
            suggestions.append("先确认缺失值是业务上的空值还是采集缺失，再决定删除、填充或保留。")
        if quality["duplicate_rows"] > 0:
            suggestions.append("有重复行时，建议先核对主键或时间戳，再决定去重。")
        if quality["empty_columns"]:
            suggestions.append(f"空列 `{', '.join(quality['empty_columns'])}` 可以优先删除。")
        if metadata["datetime_columns"] and metadata["numeric_columns"]:
            suggestions.append("如果要做趋势分析，可以先按时间列排序后再看数值变化。")
        if metadata["categorical_columns"] and metadata["numeric_columns"]:
            suggestions.append("类别列和数值列并存，适合做分组统计后再比较。")
        if not suggestions:
            suggestions.append("当前数据结构比较整齐，可以直接进入统计摘要或图表分析。")
        return suggestions

    def _build_summary(self, profile: dict[str, Any], action_name: str, message: str) -> str:
        metadata = profile["metadata"]
        quality = profile["quality"]
        if action_name == "missing_value_check":
            return f"已检查 `{metadata['filename']}` 的缺失值和重复行，共 {metadata['rows']} 行、{metadata['columns']} 列，发现 {quality['missing_cells']} 个缺失单元格。"
        if action_name == "basic_statistics":
            return f"已完成 `{metadata['filename']}` 的基础统计，当前识别到 {len(metadata['numeric_columns'])} 个数值列。"
        if action_name == "chart_suggestion":
            return f"已根据 `{metadata['filename']}` 的字段结构生成图表建议。"
        if action_name == "categorical_summary":
            return f"已整理 `{metadata['filename']}` 的类别字段频次概览。"
        if action_name == "inspect_table":
            return f"已读取 `{metadata['filename']}`，共 {metadata['rows']} 行、{metadata['columns']} 列。"
        if action_name == "export_clean_preview":
            return f"已基于 `{metadata['filename']}` 给出清洗预览建议。"
        if action_name == "simple_query_table":
            return f"我已经基于 `{metadata['filename']}` 的摘要回答你的表格问题。"
        return f"已完成 `{metadata['filename']}` 的表格摘要分析。"

    def _build_analysis_markdown(self, profile: dict[str, Any], action_name: str, message: str) -> str:
        metadata = profile["metadata"]
        quality = profile["quality"]
        statistics = profile["statistics"]
        field_table = self._build_field_table(profile["field_rows"])
        numeric_table = self._build_numeric_table(statistics["numeric_summary"])
        categorical_text = self._build_categorical_text(statistics["categorical_summary"])
        chart_lines = "\n".join(f"- {item}" for item in statistics["chart_suggestions"])
        clean_preview = "\n".join(f"- {item}" for item in self._build_clean_preview(profile))
        missing_fields = [item["name"] for item in profile["field_rows"] if item["missing"] > 0]
        notes: list[str] = []
        if metadata["rows"] > PREVIEW_ROWS:
            notes.append(f"文件较大，本轮回复只展示前 {PREVIEW_ROWS} 行摘要，不会把整张表完整展开。")
        if metadata["encoding"]:
            notes.append(f"CSV 解析编码为 `{metadata['encoding']}`。")
        if not metadata["encoding"] and metadata["sheet_names"]:
            notes.append(f"当前分析的 sheet 是 `{metadata['sheet_name']}`，可用 sheet 包括：{', '.join(metadata['sheet_names'])}。")
        if not metadata["column_names"]:
            notes.append("当前没有识别到有效列名，建议检查原始表头。")
        if not notes:
            notes.append("如果列名含义不够明确，建议补充业务背景后再继续深入分析。")

        if action_name == "simple_query_table":
            answer = self._answer_simple_query(profile, message)
            return (
                "# 表格问答结果\n\n"
                f"{answer}\n\n"
                "## 关键信息\n"
                f"- 文件名：{metadata['filename']}\n"
                f"- 行数：{metadata['rows']}\n"
                f"- 列数：{metadata['columns']}\n"
                f"- 主要字段：{'、'.join(metadata['column_names'][:8]) if metadata['column_names'] else '暂未识别'}\n"
                f"- 缺失值总数：{quality['missing_cells']}\n"
                f"- 重复行：{quality['duplicate_rows']}\n\n"
                "## 后续可继续追问\n"
                "- 你可以继续问我某一列的含义、缺失值详情、基础统计，或者适合画什么图。\n\n"
                "## 注意事项\n"
                + "\n".join(f"- {note}" for note in notes)
            )

        if action_name == "inspect_table":
            return (
                "# 表格结构检查结果\n\n"
                "## 1. 文件概况\n"
                f"- 文件名：{metadata['filename']}\n"
                f"- 文件类型：{metadata['table_type'] if 'table_type' in metadata else 'table'}\n"
                f"- 行数：{metadata['rows']}\n"
                f"- 列数：{metadata['columns']}\n"
                f"- Sheet：{metadata['sheet_name'] or '第一个 sheet / 不适用'}\n"
                f"- 编码：{metadata['encoding'] or '不适用'}\n\n"
                "## 2. 字段结构\n"
                f"{field_table}\n\n"
                "## 3. 字段类型概览\n"
                f"- 数值列：{'、'.join(metadata['numeric_columns']) if metadata['numeric_columns'] else '无'}\n"
                f"- 类别列：{'、'.join(metadata['categorical_columns']) if metadata['categorical_columns'] else '无'}\n"
                f"- 时间列：{'、'.join(metadata['datetime_columns']) if metadata['datetime_columns'] else '无'}\n\n"
                "## 4. 注意事项\n"
                + "\n".join(f"- {note}" for note in notes)
            )

        if action_name == "missing_value_check":
            return (
                "# 缺失值与数据质量检查结果\n\n"
                "## 1. 文件概况\n"
                f"- 文件名：{metadata['filename']}\n"
                f"- 行数：{metadata['rows']}\n"
                f"- 列数：{metadata['columns']}\n\n"
                "## 2. 数据质量检查\n"
                f"- 缺失值总数：{quality['missing_cells']}\n"
                f"- 重复行：{quality['duplicate_rows']}\n"
                f"- 空列：{('、'.join(quality['empty_columns']) if quality['empty_columns'] else '未发现')}\n"
                f"- 存在缺失值的字段：{('、'.join(missing_fields) if missing_fields else '未发现')}\n"
                f"- 异常提醒：{('；'.join(quality['warnings']) if quality['warnings'] else '暂无明显异常')}\n\n"
                "## 3. 字段缺失概览\n"
                f"{field_table}\n\n"
                "## 4. 清洗建议\n"
                f"{clean_preview}\n\n"
                "## 5. 注意事项\n"
                + "\n".join(f"- {note}" for note in notes)
            )

        if action_name == "basic_statistics":
            return (
                "# 基础统计结果\n\n"
                "## 1. 文件概况\n"
                f"- 文件名：{metadata['filename']}\n"
                f"- 数值列数量：{len(metadata['numeric_columns'])}\n"
                f"- 数值列：{'、'.join(metadata['numeric_columns']) if metadata['numeric_columns'] else '无'}\n\n"
                "## 2. 基础统计\n"
                f"{numeric_table}\n\n"
                "## 3. 数据质量补充\n"
                f"- 缺失值总数：{quality['missing_cells']}\n"
                f"- 重复行：{quality['duplicate_rows']}\n\n"
                "## 4. 后续建议\n"
                f"{chart_lines}\n\n"
                "## 5. 注意事项\n"
                + "\n".join(f"- {note}" for note in notes)
            )

        if action_name == "categorical_summary":
            return (
                "# 类别字段概览结果\n\n"
                "## 1. 文件概况\n"
                f"- 文件名：{metadata['filename']}\n"
                f"- 类别列数量：{len(metadata['categorical_columns'])}\n"
                f"- 类别列：{'、'.join(metadata['categorical_columns']) if metadata['categorical_columns'] else '无'}\n\n"
                "## 2. 类别字段 Top 频次\n"
                f"{categorical_text}\n\n"
                "## 3. 后续建议\n"
                "- 可以继续指定某个类别字段，单独看分组统计。\n"
                "- 如果后续要汇报，优先挑高频类别做柱状图比较。\n\n"
                "## 4. 注意事项\n"
                + "\n".join(f"- {note}" for note in notes)
            )

        if action_name == "chart_suggestion":
            return (
                "# 图表建议结果\n\n"
                "## 1. 文件概况\n"
                f"- 文件名：{metadata['filename']}\n"
                f"- 数值列：{'、'.join(metadata['numeric_columns']) if metadata['numeric_columns'] else '无'}\n"
                f"- 类别列：{'、'.join(metadata['categorical_columns']) if metadata['categorical_columns'] else '无'}\n"
                f"- 时间列：{'、'.join(metadata['datetime_columns']) if metadata['datetime_columns'] else '无'}\n\n"
                "## 2. 推荐图表\n"
                f"{chart_lines}\n\n"
                "## 3. 补充建议\n"
                "- 如果你告诉我想看趋势、对比还是分布，我可以继续帮你收窄到更合适的图。\n"
                "- 下一阶段也可以继续接 visualization-skill 直接出图。\n\n"
                "## 4. 注意事项\n"
                + "\n".join(f"- {note}" for note in notes)
            )

        if action_name == "export_clean_preview":
            return (
                "# 清洗预览建议\n\n"
                "## 1. 文件概况\n"
                f"- 文件名：{metadata['filename']}\n"
                f"- 行数：{metadata['rows']}\n"
                f"- 列数：{metadata['columns']}\n\n"
                "## 2. 清洗建议\n"
                f"{clean_preview}\n\n"
                "## 3. 数据质量摘要\n"
                f"- 缺失值总数：{quality['missing_cells']}\n"
                f"- 重复行：{quality['duplicate_rows']}\n"
                f"- 空列：{('、'.join(quality['empty_columns']) if quality['empty_columns'] else '未发现')}\n\n"
                "## 4. 注意事项\n"
                + "\n".join(f"- {note}" for note in notes)
            )

        return (
            "# 表格数据分析结果\n\n"
            "## 1. 文件概况\n"
            f"- 文件名：{metadata['filename']}\n"
            f"- 文件类型：{metadata['table_type'] if 'table_type' in metadata else 'table'}\n"
            f"- 行数：{metadata['rows']}\n"
            f"- 列数：{metadata['columns']}\n"
            f"- Sheet：{metadata['sheet_name'] or '第一个 sheet / 不适用'}\n"
            f"- 编码：{metadata['encoding'] or '不适用'}\n\n"
            "## 2. 字段结构\n"
            f"{field_table}\n\n"
            "## 3. 数据质量检查\n"
            f"- 缺失值情况：共 {quality['missing_cells']} 个缺失单元格。\n"
            f"- 重复行情况：共 {quality['duplicate_rows']} 行重复记录。\n"
            f"- 空列情况：{('、'.join(quality['empty_columns']) if quality['empty_columns'] else '未发现空列')}。\n"
            f"- 异常字段提醒：{('；'.join(quality['warnings']) if quality['warnings'] else '暂未发现明显异常字段。')}\n\n"
            "## 4. 基础统计\n"
            f"{numeric_table}\n\n"
            "## 5. 类别字段概览\n"
            f"{categorical_text}\n\n"
            "## 6. 适合的后续分析\n"
            f"{chart_lines}\n"
            f"{clean_preview}\n\n"
            "## 7. 注意事项\n"
            + "\n".join(f"- {note}" for note in notes)
        )

    def _answer_simple_query(self, profile: dict[str, Any], message: str) -> str:
        metadata = profile["metadata"]
        quality = profile["quality"]
        statistics = profile["statistics"]
        normalized = str(message or "").strip().lower()
        if any(keyword in normalized for keyword in ("主要讲什么", "主要内容", "表主要讲什么", "这个表主要讲什么")):
            return (
                "这份表格主要围绕以下字段组织："
                + "、".join(metadata["column_names"][:8])
                + f"。目前共有 {metadata['rows']} 行、{metadata['columns']} 列，"
                + ("看起来更像一个结构化业务数据表。" if metadata["categorical_columns"] else "整体更偏数值型数据表。")
            )
        if any(keyword in normalized for keyword in ("哪一列最重要", "最重要")):
            focus = metadata["numeric_columns"][:2] or metadata["categorical_columns"][:2] or metadata["column_names"][:2]
            return "从当前摘要看，建议优先关注这些字段：" + "、".join(focus) + "。如果你告诉我业务目标，我还能继续帮你判断主分析字段。"
        if any(keyword in normalized for keyword in ("每类有多少", "分类统计", "频次")):
            return "我已经按类别字段整理了 Top 频次，优先看“类别字段概览”部分会最直接。"
        if any(keyword in normalized for keyword in ("哪些字段有缺失值", "缺失值")):
            field_names = [item["name"] for item in profile["field_rows"] if item["missing"] > 0]
            return "有缺失值的字段包括：" + ("、".join(field_names) if field_names else "当前未发现有缺失值的字段。")
        if any(keyword in normalized for keyword in ("适合画什么图", "画什么图", "可视化")):
            return "我已经根据字段类型给出了图表建议，优先可以从折线图、柱状图或散点图开始。"
        if any(keyword in normalized for keyword in ("数据质量", "质量")):
            return f"当前表格共有 {quality['missing_cells']} 个缺失单元格、{quality['duplicate_rows']} 行重复记录，详细情况我已经整理到“数据质量检查”部分。"
        if any(keyword in normalized for keyword in ("平均值", "最大值", "最小值", "统计")):
            return f"当前识别到 {len(metadata['numeric_columns'])} 个数值列，我已经对这些列做了均值、标准差、中位数、最大值和最小值统计。"
        return "我已经基于表格摘要整理了文件概况、字段结构、数据质量、基础统计和图表建议，你可以继续追问某一列或某类统计。"

    def _build_next_steps(self, profile: dict[str, Any]) -> list[str]:
        metadata = profile["metadata"]
        steps = ["可以进一步做缺失值处理。", "可以选择关键数值列绘制趋势图或分布图。", "可以导出清洗后的数据预览。"]
        if metadata["numeric_columns"]:
            steps.append("如果后续需要建模，可以先确认目标列和样本量是否足够。")
        return steps[:4]

    def _tool_info(self, action_name: str, profile: dict[str, Any], success: bool, error: str) -> dict[str, Any]:
        metadata = profile["metadata"]
        return {
            "source": "skill_execution",
            "skill": self.name,
            "action": action_name,
            "filename": metadata["filename"],
            "rows": metadata["rows"],
            "columns": metadata["columns"],
            "sheet_name": metadata["sheet_name"],
            "success": bool(success),
            "error": error or "",
            "mode": "data_analysis",
        }

    def _failure_result(self, action_name: str, message: str, error: str, filename: str) -> SkillResult:
        return SkillResult(
            success=False,
            skill_name=self.name,
            action_name=action_name,
            summary=message,
            data={
                "skill": self.name,
                "action": action_name,
                "error": message,
                "analysis_markdown": message,
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
            },
            errors=[error],
        )

    def _empty_table_result(self, action_name: str, load_result: TableLoadResult, filename: str) -> SkillResult:
        message = "我识别到你上传的是表格文件，但当前表格为空，暂时没有可分析的数据内容。"
        return SkillResult(
            success=False,
            skill_name=self.name,
            action_name=action_name,
            summary=message,
            data={
                "skill": self.name,
                "action": action_name,
                "table_type": load_result.table_type,
                "analysis_markdown": message,
                "metadata": {
                    "filename": filename,
                    "rows": 0,
                    "columns": 0,
                    "sheet_name": load_result.sheet_name,
                    "encoding": load_result.encoding,
                    "column_names": [],
                    "numeric_columns": [],
                    "categorical_columns": [],
                    "datetime_columns": [],
                },
                "quality": {
                    "missing_cells": 0,
                    "duplicate_rows": 0,
                    "empty_columns": [],
                    "warnings": list(load_result.warnings or ["表格为空。"]),
                },
                "statistics": {"numeric_summary": {}, "categorical_summary": {}},
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
            },
            errors=["empty_table"],
        )
