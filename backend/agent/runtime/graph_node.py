from __future__ import annotations

import time
from abc import ABC, abstractmethod

from backend.agent.runtime.graph_events import GraphTraceEvent, NODE_STATUS_TEXT
from backend.agent.runtime.graph_errors import GraphNodeError
from backend.agent.runtime.graph_state import GraphState


class GraphNode(ABC):
    name = "node"
    status_text = "正在处理。"

    def __call__(self, state: GraphState) -> GraphState:
        started = time.perf_counter()
        state.add_trace(GraphTraceEvent(node=self.name, phase="start", summary=self.status_text))
        try:
            next_state = self.run(state)
            next_state.mark_elapsed()
            next_state.add_trace(
                GraphTraceEvent(
                    node=self.name,
                    phase="end",
                    summary=self.end_summary(next_state),
                    elapsed_ms=int((time.perf_counter() - started) * 1000),
                    data=self.trace_data(next_state),
                )
            )
            return next_state
        except Exception as exc:
            state.mark_elapsed()
            state.add_error(str(exc), node=self.name, error_type=type(exc).__name__)
            state.add_trace(
                GraphTraceEvent(
                    node=self.name,
                    phase="error",
                    status="error",
                    summary=f"{NODE_STATUS_TEXT.get(self.name, self.name)}失败：{exc}",
                    elapsed_ms=int((time.perf_counter() - started) * 1000),
                    data={"error_type": type(exc).__name__},
                )
            )
            if isinstance(exc, GraphNodeError):
                raise
            raise GraphNodeError(self.name, str(exc)) from exc

    @abstractmethod
    def run(self, state: GraphState) -> GraphState:
        raise NotImplementedError

    def end_summary(self, state: GraphState) -> str:
        return f"{NODE_STATUS_TEXT.get(self.name, self.name)}完成。"

    def trace_data(self, state: GraphState) -> dict:
        return {}
