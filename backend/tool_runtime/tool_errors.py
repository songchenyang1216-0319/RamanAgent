from __future__ import annotations

from dataclasses import dataclass


TOOL_ERROR_CODES = {
    "TOOL_NOT_FOUND",
    "ACTION_NOT_FOUND",
    "INVALID_ARGUMENTS",
    "PERMISSION_DENIED",
    "CONFIRMATION_REQUIRED",
    "CONFIRMATION_REJECTED",
    "CONFIRMATION_NOT_FOUND",
    "CONFIRMATION_APPROVED",
    "TOOL_UNAVAILABLE",
    "TOOL_TIMEOUT",
    "SANDBOX_VIOLATION",
    "MCP_SERVER_UNAVAILABLE",
    "MCP_TOOL_FAILED",
    "MODEL_UNAVAILABLE",
    "MODEL_API_ERROR",
    "RAG_INDEX_UNAVAILABLE",
    "RAG_NO_CONTEXT",
    "RAMAN_FILE_INVALID",
    "RAMAN_PIPELINE_FAILED",
    "SKILL_EXECUTION_FAILED",
    "TASK_CANCELLED",
    "UNKNOWN_ERROR",
}


@dataclass
class ToolRuntimeException(Exception):
    error_code: str
    error_message: str
    exception_type: str = ""

    def __post_init__(self) -> None:
        if self.error_code not in TOOL_ERROR_CODES:
            self.error_code = "UNKNOWN_ERROR"
        if not self.exception_type:
            self.exception_type = type(self).__name__
        super().__init__(self.error_message)


def classify_exception(exc: Exception) -> tuple[str, str]:
    text = str(exc or "").strip()
    if isinstance(exc, TimeoutError):
        return "TOOL_TIMEOUT", "工具执行超时。"
    if isinstance(exc, PermissionError):
        return "PERMISSION_DENIED", text or "权限不足，无法执行该工具。"
    if "sandbox" in text.lower() or "沙盒" in text:
        return "SANDBOX_VIOLATION", text or "沙盒策略阻止了该操作。"
    if "mcp" in text.lower():
        return "MCP_TOOL_FAILED", text or "MCP 工具执行失败。"
    if "rag" in text.lower() and "context" in text.lower():
        return "RAG_NO_CONTEXT", "资料中未找到足够依据。"
    if "raman" in text.lower() or "pipeline" in text.lower():
        return "RAMAN_PIPELINE_FAILED", text or "Raman Pipeline 执行失败。"
    return "UNKNOWN_ERROR", text or "工具执行失败。"
