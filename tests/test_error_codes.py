from __future__ import annotations

from backend.tool_runtime.tool_errors import TOOL_ERROR_CODES, ToolRuntimeException, classify_exception


def test_required_tool_error_codes_are_registered() -> None:
    expected = {
        "TOOL_NOT_FOUND",
        "ACTION_NOT_FOUND",
        "INVALID_ARGUMENTS",
        "PERMISSION_DENIED",
        "CONFIRMATION_REQUIRED",
        "CONFIRMATION_REJECTED",
        "TOOL_TIMEOUT",
        "SANDBOX_VIOLATION",
        "MCP_SERVER_UNAVAILABLE",
        "RAG_NO_CONTEXT",
        "RAMAN_PIPELINE_FAILED",
        "SKILL_EXECUTION_FAILED",
    }
    assert expected.issubset(TOOL_ERROR_CODES)


def test_unknown_tool_runtime_error_code_is_normalized() -> None:
    exc = ToolRuntimeException("NOT_A_CODE", "boom")
    assert exc.error_code == "UNKNOWN_ERROR"


def test_exception_classifier_maps_timeout() -> None:
    assert classify_exception(TimeoutError("late"))[0] == "TOOL_TIMEOUT"
