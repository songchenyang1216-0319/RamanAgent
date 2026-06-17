from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from backend.schemas.agent_stream import AgentStreamEvent


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class GraphTraceEvent:
    node: str
    phase: str
    status: str = "ok"
    summary: str = ""
    elapsed_ms: int = 0
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=_now_iso)
    visible: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


NODE_STATUS_TEXT = {
    "normalize": "正在整理消息、文件和会话上下文。",
    "context": "正在整理上下文。",
    "intent": "正在判断任务类型。",
    "planner": "正在生成计划。",
    "validate": "正在校验工具参数。",
    "execute": "正在执行工具。",
    "observe": "正在观察结果。",
    "repair": "正在修复错误。",
    "human_confirm": "正在检查是否需要人工确认。",
    "final_answer": "正在生成最终回答。",
}


def graph_trace_to_stream_event(trace: GraphTraceEvent, *, sequence: int, conversation_id: str | None, session_id: str | None) -> AgentStreamEvent:
    event = "status"
    if trace.node == "planner":
        event = "planner"
    elif trace.node == "execute":
        event = "tool_progress"
    content = trace.summary or NODE_STATUS_TEXT.get(trace.node, "正在处理。")
    return AgentStreamEvent(
        event=event,
        conversation_id=conversation_id,
        session_id=session_id,
        sequence=sequence,
        content=content,
        data={"node": trace.node, "phase": trace.phase, **dict(trace.data or {})},
        visible=trace.visible,
    )
