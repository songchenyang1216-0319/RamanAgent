from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import datetime
from threading import RLock
from typing import Any
from uuid import uuid4

from backend.db.database import get_db_connection, init_agent_memory_db


_SESSIONS_CACHE: dict[str, dict[str, Any]] = {}
_LOCK = RLock()
_MAX_MESSAGE_CHARS = 8000
_SUMMARY_MESSAGE_LIMIT = 20
_SUMMARY_RECENT_MESSAGE_LIMIT = 8


def _now_iso() -> str:
    """返回当前时间的 ISO 字符串。"""
    return datetime.now().isoformat(timespec="seconds")


def _safe_json_dumps(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return None


def _safe_json_loads(value: Any) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:
        return None


def _normalize_message_content(content: str) -> str:
    safe_content = str(content or "").strip()
    if len(safe_content) > _MAX_MESSAGE_CHARS:
        safe_content = safe_content[: _MAX_MESSAGE_CHARS - 12] + "……[已截断]"
    return safe_content


def _default_task_state() -> dict[str, Any]:
    return {
        "current_task": None,
        "current_file": None,
        "selected_skill": None,
        "selected_action": None,
        "selected_model": None,
        "pipeline": [],
        "steps_done": {
            "uploaded": False,
            "preprocessed": False,
            "predicted": False,
            "explained": False,
            "reported": False,
            "compared_history": False,
        },
        "last_prediction": None,
        "last_updated_at": None,
    }


def _merge_task_state(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in patch.items():
        if key == "steps_done" and isinstance(value, dict):
            merged.setdefault("steps_done", {}).update(value)
            continue
        if key == "pipeline" and isinstance(value, list):
            merged["pipeline"] = list(value)
            continue
        merged[key] = deepcopy(value)
    merged.setdefault("steps_done", _default_task_state()["steps_done"])
    merged.setdefault("pipeline", [])
    merged["last_updated_at"] = _now_iso()
    return merged


def _normalize_task_state(value: Any) -> dict[str, Any]:
    base = _default_task_state()
    if isinstance(value, dict):
        return _merge_task_state(base, value)
    return base


def _row_to_session_dict(row: Any, messages: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    if row is None:
        return None
    session = dict(row)
    session["last_analysis"] = _safe_json_loads(session.pop("last_analysis_json", None))
    session["task_state"] = _normalize_task_state(_safe_json_loads(session.pop("task_state_json", None)))
    session["messages"] = messages if messages is not None else []
    session["message_count"] = len(session["messages"])
    session["is_deleted"] = bool(session.get("is_deleted"))
    return session


def _row_to_message_dict(row: Any) -> dict[str, Any]:
    item = dict(row)
    payload = {
        "role": item.get("role"),
        "content": item.get("content"),
        "created_at": item.get("created_at"),
    }
    metadata = _safe_json_loads(item.get("metadata_json"))
    if metadata is not None:
        payload["metadata"] = metadata
    return payload


def _fetch_session_row(connection, session_id: str):
    return connection.execute(
        "SELECT * FROM agent_sessions WHERE session_id = ? LIMIT 1",
        (session_id,),
    ).fetchone()


def _fetch_messages(connection, session_id: str, limit: int | None = None) -> list[dict[str, Any]]:
    sql = "SELECT role, content, metadata_json, created_at FROM agent_messages WHERE session_id = ? ORDER BY datetime(created_at) ASC, id ASC"
    params: list[Any] = [session_id]
    if limit is not None and limit > 0:
        sql += " LIMIT ?"
        params.append(int(limit))
    rows = connection.execute(sql, params).fetchall()
    return [_row_to_message_dict(row) for row in rows]


def _count_messages(connection, session_id: str) -> int:
    row = connection.execute(
        "SELECT COUNT(*) AS count FROM agent_messages WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    return int(row["count"] if row is not None else 0)


def _refresh_cache(session: dict[str, Any]) -> dict[str, Any]:
    _SESSIONS_CACHE[str(session.get("session_id"))] = deepcopy(session)
    return deepcopy(session)


def _build_summary_from_messages(messages: list[dict[str, Any]], last_analysis: dict[str, Any] | None = None) -> str:
    if not messages:
        return ""
    recent_messages = messages[-_SUMMARY_RECENT_MESSAGE_LIMIT :]
    user_messages = [str(item.get("content") or "").strip() for item in recent_messages if str(item.get("role") or "") == "user"]
    assistant_messages = [str(item.get("content") or "").strip() for item in recent_messages if str(item.get("role") or "") == "assistant"]
    if last_analysis and isinstance(last_analysis, dict):
        analysis_hint = str(
            last_analysis.get("llm_explanation")
            or last_analysis.get("reply")
            or last_analysis.get("message")
            or ""
        ).strip()
    else:
        analysis_hint = ""

    text_blob = " ".join(user_messages[-3:] + assistant_messages[-2:] + [analysis_hint])
    keywords = []
    for token in re.findall(r"[A-Za-z0-9_]{3,}|[\u4e00-\u9fff]{2,}", text_blob):
        lowered = token.lower().strip()
        if len(lowered) < 2:
            continue
        if lowered in {"the", "and", "for", "with", "from", "this", "that", "分析", "结果", "文件", "内容"}:
            continue
        if lowered not in keywords:
            keywords.append(lowered)
        if len(keywords) >= 6:
            break

    preview_parts = []
    if user_messages:
        preview_parts.append(f"最近用户问题：{user_messages[-1][:60]}")
    if assistant_messages:
        preview_parts.append(f"最近助手回复：{assistant_messages[-1][:60]}")
    if keywords:
        preview_parts.append(f"关键词：{'、'.join(keywords)}")
    if last_analysis:
        preview_parts.append(
            "最近分析："
            + str(
                last_analysis.get("llm_explanation")
                or last_analysis.get("reply")
                or last_analysis.get("message")
                or ""
            ).strip()[:120]
        )
    summary = "；".join(part for part in preview_parts if part).strip("；")
    return summary[:500]


def _maybe_refresh_summary(connection, session_id: str) -> None:
    message_count = _count_messages(connection, session_id)
    if message_count <= _SUMMARY_MESSAGE_LIMIT:
        return
    row = _fetch_session_row(connection, session_id)
    if row is None:
        return
    messages = _fetch_messages(connection, session_id, limit=12)
    last_analysis = _safe_json_loads(row["last_analysis_json"])
    summary = _build_summary_from_messages(messages, last_analysis=last_analysis if isinstance(last_analysis, dict) else None)
    if not summary:
        return
    now = _now_iso()
    connection.execute(
        "UPDATE agent_sessions SET summary = ?, updated_at = ? WHERE session_id = ?",
        (summary, now, session_id),
    )


def _load_session(session_id: str) -> dict[str, Any] | None:
    init_agent_memory_db()
    with _LOCK:
        connection = get_db_connection()
        try:
            row = _fetch_session_row(connection, session_id)
            if row is None or bool(row["is_deleted"]):
                return None
            messages = _fetch_messages(connection, session_id)
            session = _row_to_session_dict(row, messages=messages)
            if session is None:
                return None
            return _refresh_cache(session)
        finally:
            connection.close()


def create_session(session_id: str | None = None) -> dict:
    """创建或返回一个会话。"""
    init_agent_memory_db()
    with _LOCK:
        resolved_session_id = str(session_id or uuid4())
        connection = get_db_connection()
        try:
            row = _fetch_session_row(connection, resolved_session_id)
            now = _now_iso()
            if row is None:
                connection.execute(
                    """
                    INSERT INTO agent_sessions (
                        session_id, title, created_at, updated_at,
                        last_analysis_json, last_file, last_report, task_state_json, summary, is_deleted
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (
                        resolved_session_id,
                        None,
                        now,
                        now,
                        None,
                        None,
                        None,
                        _safe_json_dumps(_default_task_state()),
                        "",
                    ),
                )
            else:
                connection.execute(
                    "UPDATE agent_sessions SET is_deleted = 0, updated_at = ? WHERE session_id = ?",
                    (now, resolved_session_id),
                )
            connection.commit()
            session = get_session(resolved_session_id)
            if session is None:
                session = _load_session(resolved_session_id)
            if session is None:
                session = {
                    "session_id": resolved_session_id,
                    "created_at": now,
                    "updated_at": now,
                    "messages": [],
                    "last_analysis": None,
                    "last_file": None,
                    "last_report": None,
                    "task_state": _default_task_state(),
                    "summary": "",
                    "title": None,
                    "is_deleted": False,
                    "message_count": 0,
                }
            return deepcopy(session)
        finally:
            connection.close()


def get_session(session_id: str) -> dict | None:
    """读取会话。"""
    resolved_session_id = str(session_id or "").strip()
    if not resolved_session_id:
        return None
    return _load_session(resolved_session_id)


def update_session(session_id: str, key: str, value) -> dict:
    """更新会话中的一个顶层字段。"""
    init_agent_memory_db()
    with _LOCK:
        resolved_session_id = str(session_id or "").strip()
        if not resolved_session_id:
            raise ValueError("session_id 不能为空。")
        session = create_session(resolved_session_id)
        now = _now_iso()
        connection = get_db_connection()
        try:
            if key == "last_analysis":
                connection.execute(
                    "UPDATE agent_sessions SET last_analysis_json = ?, updated_at = ?, is_deleted = 0 WHERE session_id = ?",
                    (_safe_json_dumps(value), now, resolved_session_id),
                )
                session["last_analysis"] = deepcopy(value)
            elif key == "last_file":
                connection.execute(
                    "UPDATE agent_sessions SET last_file = ?, updated_at = ?, is_deleted = 0 WHERE session_id = ?",
                    (None if value in {None, ""} else str(value), now, resolved_session_id),
                )
                session["last_file"] = None if value in {None, ""} else str(value)
            elif key == "last_report":
                connection.execute(
                    "UPDATE agent_sessions SET last_report = ?, updated_at = ?, is_deleted = 0 WHERE session_id = ?",
                    (None if value in {None, ""} else str(value), now, resolved_session_id),
                )
                session["last_report"] = None if value in {None, ""} else str(value)
            elif key == "task_state":
                task_state = _normalize_task_state(value)
                connection.execute(
                    "UPDATE agent_sessions SET task_state_json = ?, updated_at = ?, is_deleted = 0 WHERE session_id = ?",
                    (_safe_json_dumps(task_state), now, resolved_session_id),
                )
                session["task_state"] = task_state
            elif key == "summary":
                connection.execute(
                    "UPDATE agent_sessions SET summary = ?, updated_at = ?, is_deleted = 0 WHERE session_id = ?",
                    (None if value in {None, ""} else str(value), now, resolved_session_id),
                )
                session["summary"] = None if value in {None, ""} else str(value)
            elif key == "title":
                connection.execute(
                    "UPDATE agent_sessions SET title = ?, updated_at = ?, is_deleted = 0 WHERE session_id = ?",
                    (None if value in {None, ""} else str(value), now, resolved_session_id),
                )
                session["title"] = None if value in {None, ""} else str(value)
            elif key == "is_deleted":
                connection.execute(
                    "UPDATE agent_sessions SET is_deleted = ?, updated_at = ? WHERE session_id = ?",
                    (1 if bool(value) else 0, now, resolved_session_id),
                )
                session["is_deleted"] = bool(value)
            else:
                session[key] = deepcopy(value)
            connection.commit()
            session["updated_at"] = now
            _refresh_cache(session)
            return deepcopy(session)
        finally:
            connection.close()


def get_last_analysis(session_id: str) -> dict | None:
    """获取最近一次分析结果。"""
    session = get_session(session_id)
    if session is None:
        return None
    return deepcopy(session.get("last_analysis"))


def get_task_state(session_id: str) -> dict | None:
    """获取任务状态。"""
    session = get_session(session_id)
    if session is None:
        return None
    task_state = session.get("task_state")
    return deepcopy(task_state) if isinstance(task_state, dict) else _default_task_state()


def update_task_state(session_id: str, patch: dict[str, Any] | None) -> dict:
    """按 patch 合并更新任务状态。"""
    init_agent_memory_db()
    with _LOCK:
        current_state = get_task_state(session_id) or _default_task_state()
        if not isinstance(patch, dict):
            patch = {}
        merged_state = _merge_task_state(current_state, patch)
        return update_session(session_id, "task_state", merged_state)


def build_task_state_response(session_id: str) -> dict:
    """把任务状态整理成给前端展示的轻量响应。"""
    session = get_session(session_id)
    task_state = (session or {}).get("task_state") or _default_task_state()
    steps_done = dict(task_state.get("steps_done") or {})
    completed = [name for name, flag in steps_done.items() if bool(flag)]
    pending = [name for name, flag in steps_done.items() if not bool(flag)]
    next_step = pending[0] if pending else None
    return {
        "session_id": session_id,
        "current_task": task_state.get("current_task"),
        "current_file": task_state.get("current_file"),
        "selected_skill": task_state.get("selected_skill"),
        "selected_action": task_state.get("selected_action"),
        "selected_model": task_state.get("selected_model"),
        "pipeline": list(task_state.get("pipeline") or []),
        "steps_done": steps_done,
        "completed_steps": completed,
        "pending_steps": pending,
        "next_step": next_step,
        "last_prediction": task_state.get("last_prediction"),
        "last_updated_at": task_state.get("last_updated_at"),
        "summary": (session or {}).get("summary") or "",
    }


def get_recent_messages(session_id: str, limit: int = 8) -> list[dict]:
    """读取最近 N 条消息，按时间正序返回。"""
    resolved_session_id = str(session_id or "").strip()
    if not resolved_session_id:
        return []
    init_agent_memory_db()
    with _LOCK:
        connection = get_db_connection()
        try:
            limit = max(int(limit or 0), 0)
            sql = "SELECT role, content, metadata_json, created_at FROM agent_messages WHERE session_id = ? ORDER BY datetime(created_at) DESC, id DESC"
            params: list[Any] = [resolved_session_id]
            if limit > 0:
                sql += " LIMIT ?"
                params.append(limit)
            rows = connection.execute(sql, params).fetchall()
            items = [_row_to_message_dict(row) for row in rows]
            items.reverse()
            return items
        finally:
            connection.close()


def append_message(session_id: str, role: str, content: str, metadata: dict | None = None) -> dict:
    """向消息历史追加一条轻量消息。"""
    init_agent_memory_db()
    with _LOCK:
        session = create_session(session_id)
        resolved_session_id = str(session["session_id"])
        safe_content = _normalize_message_content(content)
        now = _now_iso()
        connection = get_db_connection()
        try:
            connection.execute(
                """
                INSERT INTO agent_messages (session_id, role, content, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    resolved_session_id,
                    str(role or "user"),
                    safe_content,
                    _safe_json_dumps(metadata),
                    now,
                ),
            )
            connection.execute(
                "UPDATE agent_sessions SET updated_at = ?, is_deleted = 0 WHERE session_id = ?",
                (now, resolved_session_id),
            )
            _maybe_refresh_summary(connection, resolved_session_id)
            connection.commit()
            refreshed = get_session(resolved_session_id)
            if refreshed is None:
                refreshed = session
            return deepcopy(refreshed)
        finally:
            connection.close()


def clear_session_memory(session_id: str) -> dict:
    """清空某个 session 的对话与分析记忆，但保留 session 本身。"""
    init_agent_memory_db()
    with _LOCK:
        resolved_session_id = str(session_id or "").strip()
        if not resolved_session_id:
            raise ValueError("session_id 不能为空。")
        create_session(resolved_session_id)
        now = _now_iso()
        connection = get_db_connection()
        try:
            connection.execute("DELETE FROM agent_messages WHERE session_id = ?", (resolved_session_id,))
            connection.execute(
                """
                UPDATE agent_sessions
                SET last_analysis_json = NULL,
                    last_file = NULL,
                    last_report = NULL,
                    task_state_json = ?,
                    summary = NULL,
                    updated_at = ?,
                    is_deleted = 0
                WHERE session_id = ?
                """,
                (_safe_json_dumps(_default_task_state()), now, resolved_session_id),
            )
            connection.commit()
            _SESSIONS_CACHE.pop(resolved_session_id, None)
            return deepcopy(get_session(resolved_session_id) or create_session(resolved_session_id))
        finally:
            connection.close()


def delete_session(session_id: str) -> dict:
    """软删除某个 session。"""
    init_agent_memory_db()
    with _LOCK:
        resolved_session_id = str(session_id or "").strip()
        if not resolved_session_id:
            raise ValueError("session_id 不能为空。")
        create_session(resolved_session_id)
        now = _now_iso()
        connection = get_db_connection()
        try:
            connection.execute(
                "UPDATE agent_sessions SET is_deleted = 1, updated_at = ? WHERE session_id = ?",
                (now, resolved_session_id),
            )
            connection.commit()
            _SESSIONS_CACHE.pop(resolved_session_id, None)
            session = _load_session(resolved_session_id)
            return deepcopy(session) if session is not None else {
                "session_id": resolved_session_id,
                "is_deleted": True,
                "updated_at": now,
            }
        finally:
            connection.close()


def clear_sessions() -> None:
    """清空内存缓存，仅用于测试。"""
    with _LOCK:
        _SESSIONS_CACHE.clear()
