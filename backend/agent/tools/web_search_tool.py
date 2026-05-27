"""联网搜索工具兼容层。"""

from __future__ import annotations

from typing import Any

from backend.skills.registry import execute_skill


def web_search_tool(query: str, limit: int = 5) -> dict:
    """执行一次联网搜索，并返回可供 Agent 总结的结果。"""
    query = str(query or "").strip()
    if not query:
        return {"success": False, "error_message": "搜索关键词不能为空。", "items": []}
    skill_result = execute_skill("web-search", action_name="search", query=query, max_results=max(1, min(int(limit or 5), 10)))
    payload = skill_result.to_dict()
    data = dict(payload.get("data") or {})
    items = list(data.get("items") or [])
    payload.update(
        {
            "query": data.get("query") or query,
            "total": data.get("total", len(items)),
            "items": items,
            "source": data.get("source") or data.get("used_provider") or "web_search_skill",
            "used_provider": data.get("used_provider") or data.get("provider") or data.get("source"),
            "answer": data.get("answer"),
            "request_id": data.get("request_id"),
            "response_time": data.get("response_time"),
            "error_code": data.get("error_code"),
            "error_message": data.get("message") or payload.get("summary") or (payload.get("errors") or [None])[0],
            "suggestion": data.get("suggestion"),
        }
    )
    return payload
