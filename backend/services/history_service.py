"""分析历史与实验记录服务。"""

from __future__ import annotations

from datetime import datetime
import json
import sqlite3
import uuid

from backend.db.database import get_db_connection


BASE_COLUMNS = {
    "id": "INTEGER PRIMARY KEY AUTOINCREMENT",
    "task_id": "TEXT UNIQUE",
    "sample_file": "TEXT",
    "saved_file": "TEXT",
    "sample_path": "TEXT",
    "svr_prediction": "REAL",
    "rf_prediction": "REAL",
    "fusion_prediction": "REAL",
    "unit": "TEXT",
    "confidence_status": "TEXT",
    "knn_distance": "REAL",
    "confidence_threshold": "REAL",
    "model_abs_diff": "REAL",
    "model_rel_diff": "REAL",
    "model_warning": "INTEGER",
    "model_message": "TEXT",
    "llm_explanation": "TEXT",
    "report_file": "TEXT",
    "report_path": "TEXT",
    "raw_figure_url": "TEXT",
    "preprocessed_figure_url": "TEXT",
    "cdae_figure_url": "TEXT",
    "final_figure_url": "TEXT",
    "pipeline_text": "TEXT",
    "expected_value": "REAL",
    "prediction_error": "REAL",
    "created_at": "TEXT",
}

EXTRA_COLUMNS = {
    "model_version": "TEXT",
    "professional_overall_level": "TEXT",
    "quality_level": "TEXT",
    "baseline_level": "TEXT",
    "peak_count": "INTEGER",
    "operator": "TEXT",
    "sample_name": "TEXT",
    "sample_type": "TEXT",
    "concentration_label": "REAL",
    "instrument": "TEXT",
    "laser_power": "TEXT",
    "integration_time": "TEXT",
    "remarks": "TEXT",
    "model_info_json": "TEXT",
    "result_json": "TEXT",
    "professional_analysis_json": "TEXT",
    "experiment_metadata_json": "TEXT",
    "report_json": "TEXT",
    "web_urls_json": "TEXT",
}


def init_history_db(db_path=None) -> None:
    """初始化历史记录数据库和兼容迁移。"""
    connection = get_db_connection(db_path)
    try:
        ordered_columns = {**BASE_COLUMNS, **EXTRA_COLUMNS}
        column_sql = ",\n                ".join(f"{name} {definition}" for name, definition in ordered_columns.items())
        connection.execute(
            f"""
            CREATE TABLE IF NOT EXISTS analysis_history (
                {column_sql}
            )
            """
        )
        existing_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(analysis_history)").fetchall()
        }
        for name, definition in EXTRA_COLUMNS.items():
            if name not in existing_columns:
                connection.execute(f"ALTER TABLE analysis_history ADD COLUMN {name} {definition}")
        connection.commit()
    finally:
        connection.close()


def parse_expected_value_from_filename(file_name: str) -> float | None:
    """从文件名中解析疑似真实浓度值。"""
    import re

    if not file_name:
        return None
    match = re.search(r"-(\d+(?:\.\d+)?)-", str(file_name))
    return float(match.group(1)) if match else None


def _to_json(value) -> str | None:
    if value is None:
        return None
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return None


def _from_json(value):
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:
        return None


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    """将 sqlite 行对象转换为 API 友好的字典。"""
    if row is None:
        return None
    item = dict(row)
    item["model_warning"] = bool(item.get("model_warning"))
    item["model_info"] = _from_json(item.pop("model_info_json", None))
    item["result"] = _from_json(item.pop("result_json", None))
    item["professional_analysis"] = _from_json(item.pop("professional_analysis_json", None))
    item["experiment_metadata"] = _from_json(item.pop("experiment_metadata_json", None))
    item["report"] = _from_json(item.pop("report_json", None))
    item["web_urls"] = _from_json(item.pop("web_urls_json", None))
    return item


def save_analysis_history(payload: dict, db_path=None) -> dict:
    """保存一次完整分析任务的历史记录。"""
    init_history_db(db_path)
    result = payload.get("result", {}) or {}
    professional_analysis = payload.get("professional_analysis", {}) or {}
    model_info = payload.get("model_info", {}) or {}
    experiment_metadata = payload.get("experiment_metadata", {}) or {}
    confidence = result.get("confidence", {}) or {}
    disagreement = result.get("model_disagreement", {}) or {}
    report = payload.get("report", {}) or {}
    web_urls = payload.get("web_urls", {}) or {}
    figure_urls = web_urls.get("figures", {}) or {}
    summary = professional_analysis.get("professional_summary", {}) or {}
    quality_analysis = professional_analysis.get("quality_analysis", {}) or {}
    baseline_analysis = professional_analysis.get("baseline_analysis", {}) or {}
    peak_analysis = professional_analysis.get("peak_analysis", {}) or {}

    task_id = str(uuid.uuid4())
    created_at = datetime.now().isoformat(timespec="seconds")
    sample_file = str(result.get("sample_file", "") or "")
    expected_value = result.get("expected_value_from_filename")
    if expected_value is None:
        expected_value = parse_expected_value_from_filename(sample_file)
    prediction_error = result.get("prediction_error_from_filename")
    final_prediction = result.get("fusion_prediction", result.get("final_prediction"))
    if prediction_error is None and expected_value is not None and final_prediction is not None:
        prediction_error = float(final_prediction) - float(expected_value)

    connection = get_db_connection(db_path)
    try:
        connection.execute(
            """
            INSERT INTO analysis_history (
                task_id, sample_file, saved_file, sample_path,
                svr_prediction, rf_prediction, fusion_prediction, unit,
                confidence_status, knn_distance, confidence_threshold,
                model_abs_diff, model_rel_diff, model_warning, model_message,
                llm_explanation, report_file, report_path,
                raw_figure_url, preprocessed_figure_url, cdae_figure_url, final_figure_url,
                pipeline_text, expected_value, prediction_error, created_at,
                model_version, professional_overall_level, quality_level, baseline_level, peak_count,
                operator, sample_name, sample_type, concentration_label, instrument, laser_power,
                integration_time, remarks, model_info_json, result_json, professional_analysis_json,
                experiment_metadata_json, report_json, web_urls_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                sample_file,
                payload.get("saved_file"),
                result.get("sample_path"),
                result.get("svr_prediction"),
                result.get("rf_prediction"),
                final_prediction,
                result.get("unit"),
                confidence.get("status"),
                confidence.get("knn_distance"),
                confidence.get("threshold"),
                disagreement.get("absolute_difference"),
                disagreement.get("relative_difference"),
                1 if disagreement.get("warning") else 0,
                disagreement.get("message"),
                payload.get("llm_explanation"),
                report.get("report_file"),
                report.get("report_path"),
                figure_urls.get("raw"),
                figure_urls.get("preprocessed"),
                figure_urls.get("cdae"),
                figure_urls.get("final"),
                " → ".join(result.get("pipeline", []) or []),
                expected_value,
                prediction_error,
                created_at,
                model_info.get("model_version"),
                summary.get("overall_level"),
                quality_analysis.get("quality_level"),
                baseline_analysis.get("baseline_level"),
                peak_analysis.get("peak_count"),
                experiment_metadata.get("operator"),
                experiment_metadata.get("sample_name"),
                experiment_metadata.get("sample_type"),
                expected_value,
                experiment_metadata.get("instrument"),
                experiment_metadata.get("laser_power"),
                experiment_metadata.get("integration_time"),
                experiment_metadata.get("remarks"),
                _to_json(model_info),
                _to_json(result),
                _to_json(professional_analysis),
                _to_json(experiment_metadata),
                _to_json(report),
                _to_json(web_urls),
            ),
        )
        connection.commit()
    finally:
        connection.close()

    return {"task_id": task_id, "created_at": created_at}


def list_analysis_history(
    limit: int = 20,
    offset: int = 0,
    db_path=None,
    keyword: str | None = None,
    model_version: str | None = None,
    min_prediction: float | None = None,
    max_prediction: float | None = None,
    quality_level: str | None = None,
    baseline_level: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """按时间倒序返回历史记录摘要列表，并支持轻量筛选。"""
    init_history_db(db_path)
    connection = get_db_connection(db_path)
    try:
        where_clauses = []
        params: list = []

        if keyword:
            where_clauses.append("(sample_file LIKE ? OR sample_name LIKE ? OR remarks LIKE ?)")
            like = f"%{keyword}%"
            params.extend([like, like, like])
        if model_version:
            where_clauses.append("model_version = ?")
            params.append(model_version)
        if min_prediction is not None:
            where_clauses.append("fusion_prediction >= ?")
            params.append(min_prediction)
        if max_prediction is not None:
            where_clauses.append("fusion_prediction <= ?")
            params.append(max_prediction)
        if quality_level:
            where_clauses.append("quality_level = ?")
            params.append(quality_level)
        if baseline_level:
            where_clauses.append("baseline_level = ?")
            params.append(baseline_level)
        if start_date:
            where_clauses.append("created_at >= ?")
            params.append(start_date)
        if end_date:
            where_clauses.append("created_at <= ?")
            params.append(end_date)

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        total = connection.execute(
            f"SELECT COUNT(*) AS count FROM analysis_history {where_sql}",
            params,
        ).fetchone()["count"]
        rows = connection.execute(
            f"""
            SELECT task_id, sample_file, sample_name, sample_type, fusion_prediction, unit, confidence_status,
                   model_warning, model_message, report_file, created_at, model_version,
                   professional_overall_level, quality_level, baseline_level, peak_count
            FROM analysis_history
            {where_sql}
            ORDER BY datetime(created_at) DESC, id DESC
            LIMIT ? OFFSET ?
            """,
            params + [limit, offset],
        ).fetchall()
    finally:
        connection.close()

    items = [_row_to_dict(row) for row in rows]
    return {"total": int(total), "items": items}


def get_analysis_history(task_id: str, db_path=None) -> dict | None:
    """获取单条历史记录详情。"""
    init_history_db(db_path)
    connection = get_db_connection(db_path)
    try:
        row = connection.execute(
            "SELECT * FROM analysis_history WHERE task_id = ?",
            (task_id,),
        ).fetchone()
    finally:
        connection.close()
    return _row_to_dict(row)


def delete_analysis_history(task_id: str, db_path=None) -> bool:
    """删除单条历史记录，仅删除数据库记录。"""
    init_history_db(db_path)
    connection = get_db_connection(db_path)
    try:
        cursor = connection.execute("DELETE FROM analysis_history WHERE task_id = ?", (task_id,))
        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()

