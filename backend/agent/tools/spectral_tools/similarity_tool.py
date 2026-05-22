"""历史样品相似性比较工具。"""

from __future__ import annotations

from backend.services.history_service import list_analysis_history


def find_similar_history(current_prediction_result: dict, limit: int = 5, max_difference: float | None = None) -> dict:
    """基于预测浓度查找接近的历史样品。"""
    try:
        current_value = current_prediction_result.get("final_prediction")
        if current_value is None:
            current_value = current_prediction_result.get("fusion_prediction")
        if current_value is None:
            return {
                "success": False,
                "similar_records": [],
                "message": "当前预测结果缺少融合预测值，无法比较历史样品。",
            }
        current_value = float(current_value)
        threshold = float(max_difference) if max_difference is not None else max(2.0, abs(current_value) * 0.1)
        history = list_analysis_history(limit=100, offset=0)
        records = []
        for item in history.get("items", []):
            sample_file = str(item.get("sample_file", "") or "")
            lowered = sample_file.lower()
            if any(token in lowered for token in ("mock", "test", "demo")):
                continue
            value = item.get("fusion_prediction")
            if value is None:
                continue
            try:
                difference = abs(float(value) - current_value)
            except (TypeError, ValueError):
                continue
            if difference > threshold:
                continue
            records.append(
                {
                    "task_id": item.get("task_id"),
                    "sample_file": sample_file,
                    "final_prediction": float(value),
                    "difference": float(difference),
                    "created_at": item.get("created_at"),
                }
            )

        records.sort(key=lambda item: item["difference"])
        similar_records = records[: max(1, int(limit))]
        if not similar_records:
            return {
                "success": True,
                "similar_records": [],
                "message": "暂无预测浓度接近的历史记录。",
            }
        return {
            "success": True,
            "similar_records": similar_records,
            "message": f"找到 {len(similar_records)} 条预测浓度接近的历史记录。",
        }
    except Exception as exc:
        return {"success": False, "similar_records": [], "message": f"历史相似样品比较失败: {exc}"}
