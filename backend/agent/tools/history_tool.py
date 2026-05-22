"""历史记录工具。"""

from __future__ import annotations

from backend.services.history_service import get_analysis_history, list_analysis_history


def list_history_tool(limit: int = 20, offset: int = 0) -> dict:
    """列出历史分析记录。"""
    data = list_analysis_history(limit=limit, offset=offset)
    return {
        "success": True,
        "total": data.get("total", 0),
        "items": data.get("items", []),
        "limit": limit,
        "offset": offset,
    }


def get_history_detail_tool(history_id: str) -> dict:
    """查询单条历史记录。"""
    item = get_analysis_history(history_id)
    if item is None:
        return {
            "success": False,
            "history_id": history_id,
            "error_message": f"未找到历史记录: {history_id}",
        }
    return {"success": True, "history_id": history_id, "item": item}
