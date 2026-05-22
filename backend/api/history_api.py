"""分析历史记录接口。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.services.history_service import delete_analysis_history, get_analysis_history, list_analysis_history


router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("")
def history_list(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    keyword: str | None = Query(default=None),
    model_version: str | None = Query(default=None),
    min_prediction: float | None = Query(default=None),
    max_prediction: float | None = Query(default=None),
    quality_level: str | None = Query(default=None),
    baseline_level: str | None = Query(default=None),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
) -> dict:
    """获取历史记录列表。"""
    data = list_analysis_history(
        limit=limit,
        offset=offset,
        keyword=keyword,
        model_version=model_version,
        min_prediction=min_prediction,
        max_prediction=max_prediction,
        quality_level=quality_level,
        baseline_level=baseline_level,
        start_date=start_date,
        end_date=end_date,
    )
    return {"success": True, "total": data["total"], "items": data["items"]}


@router.get("/{task_id}")
def history_detail(task_id: str) -> dict:
    """获取单条历史记录详情。"""
    item = get_analysis_history(task_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"历史记录不存在: {task_id}")
    return {"success": True, "item": item}


@router.delete("/{task_id}")
def history_delete(task_id: str) -> dict:
    """删除单条历史记录，仅删除数据库记录。"""
    deleted = delete_analysis_history(task_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"历史记录不存在: {task_id}")
    return {"success": True, "task_id": task_id}
