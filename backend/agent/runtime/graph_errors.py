from __future__ import annotations


class GraphRuntimeError(RuntimeError):
    """Base error for the Agent graph runtime."""


class GraphNodeError(GraphRuntimeError):
    """Raised when one graph node fails unexpectedly."""

    def __init__(self, node_name: str, message: str) -> None:
        super().__init__(f"{node_name}: {message}")
        self.node_name = node_name
        self.message = message


class GraphFallbackRequested(GraphRuntimeError):
    """Raised when graph execution intentionally hands off to legacy runtime."""

    def __init__(self, reason: str = "Graph Runtime 请求回退旧编排。") -> None:
        super().__init__(reason)
        self.reason = reason
