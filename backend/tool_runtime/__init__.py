from __future__ import annotations

from .tool_context import ToolContext
from .tool_result import ToolResult

__all__ = ["ToolContext", "ToolResult", "ToolRuntime"]


def __getattr__(name: str):
    if name == "ToolRuntime":
        from .tool_runtime import ToolRuntime

        return ToolRuntime
    raise AttributeError(name)
