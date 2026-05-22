"""轻量级内存会话上下文存储。"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from threading import Lock
from uuid import uuid4


_SESSIONS: dict[str, dict] = {}
_LOCK = Lock()


def _now_iso() -> str:
    """返回当前时间的 ISO 字符串。"""
    return datetime.now().isoformat(timespec="seconds")


def _build_session(session_id: str) -> dict:
    """构造新的会话对象。"""
    timestamp = _now_iso()
    return {
        "session_id": session_id,
        "created_at": timestamp,
        "updated_at": timestamp,
        "messages": [],
        "last_analysis": None,
        "last_file": None,
        "last_report": None,
    }


def create_session(session_id: str | None = None) -> dict:
    """创建或返回一个会话。"""
    with _LOCK:
        resolved_session_id = str(session_id or uuid4())
        session = _SESSIONS.get(resolved_session_id)
        if session is None:
            session = _build_session(resolved_session_id)
            _SESSIONS[resolved_session_id] = session
        return deepcopy(session)


def get_session(session_id: str) -> dict | None:
    """读取会话。"""
    with _LOCK:
        session = _SESSIONS.get(str(session_id))
        return deepcopy(session) if session is not None else None


def update_session(session_id: str, key: str, value) -> dict:
    """更新会话中的一个顶层字段。"""
    with _LOCK:
        resolved_session_id = str(session_id)
        session = _SESSIONS.get(resolved_session_id)
        if session is None:
            session = _build_session(resolved_session_id)
            _SESSIONS[resolved_session_id] = session
        session[key] = deepcopy(value)
        session["updated_at"] = _now_iso()
        return deepcopy(session)


def get_last_analysis(session_id: str) -> dict | None:
    """获取最近一次分析结果。"""
    session = get_session(session_id)
    if session is None:
        return None
    return session.get("last_analysis")


def append_message(session_id: str, role: str, content: str) -> dict:
    """向消息历史追加一条轻量消息。"""
    safe_content = str(content or "").strip()
    if len(safe_content) > 2000:
        safe_content = safe_content[:2000] + "..."

    with _LOCK:
        resolved_session_id = str(session_id)
        session = _SESSIONS.get(resolved_session_id)
        if session is None:
            session = _build_session(resolved_session_id)
            _SESSIONS[resolved_session_id] = session
        session["messages"].append(
            {
                "role": str(role or "user"),
                "content": safe_content,
                "created_at": _now_iso(),
            }
        )
        session["updated_at"] = _now_iso()
        return deepcopy(session)


def clear_sessions() -> None:
    """清空内存会话，仅用于测试。"""
    with _LOCK:
        _SESSIONS.clear()
