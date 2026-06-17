from __future__ import annotations

import time

from backend.agent.planning.tool_catalog import ToolCatalog
from backend.agent.planning.tool_schema import ActionSchema, ToolSchema
from backend.repositories.audit_log_repository import AuditLogRepository
from backend.tool_runtime import ToolContext, ToolRuntime
from backend.tool_runtime.tool_confirmation import CONFIRMATION_STORE, update_confirmation_status
from backend.tool_runtime.tool_result import ToolResult


def _context() -> ToolContext:
    return ToolContext(user_id="unit_user", conversation_id="unit_conv", file_ids=["file_ok"], metadata={"role": "admin"}, permissions=["*"])


def _runtime_with_custom_tool(action: ActionSchema | None = None, *, available: bool = True, source: str = "builtin") -> ToolRuntime:
    catalog = ToolCatalog()
    catalog._tools["unit_tool"] = ToolSchema(
        tool_name="unit_tool",
        display_name="Unit Tool",
        description="unit",
        category="test",
        source=source,
        available=available,
        unavailable_reason="unit unavailable",
        actions={
            "run": action
            or ActionSchema(
                action_name="run",
                description="run",
                input_schema={"type": "object", "properties": {}},
                side_effects=["none"],
            )
        },
    )
    return ToolRuntime(catalog=catalog)


def test_tool_not_found_returns_error() -> None:
    result = ToolRuntime().execute("missing_tool", "run", {}, _context())
    assert result.success is False
    assert result.error_code == "TOOL_NOT_FOUND"
    assert result.error_message
    assert result.elapsed_ms >= 0


def test_action_not_found_returns_error() -> None:
    result = ToolRuntime().execute("model_tool", "missing_action", {}, _context())
    assert result.success is False
    assert result.error_code == "ACTION_NOT_FOUND"


def test_tool_unavailable_and_mcp_unavailable_codes() -> None:
    result = _runtime_with_custom_tool(available=False).execute("unit_tool", "run", {}, _context())
    assert result.error_code == "TOOL_UNAVAILABLE"
    mcp_result = _runtime_with_custom_tool(available=False, source="mcp").execute("unit_tool", "run", {}, _context())
    assert mcp_result.error_code == "MCP_SERVER_UNAVAILABLE"


def test_required_and_schema_argument_validation() -> None:
    missing = ToolRuntime().execute("table_tool", "analyze_table", {}, _context())
    assert missing.success is False
    assert missing.error_code == "INVALID_ARGUMENTS"
    wrong_type = ToolRuntime().execute("table_tool", "analyze_table", {"query": 123}, _context())
    assert wrong_type.success is False
    assert wrong_type.error_code == "INVALID_ARGUMENTS"


def test_file_scope_blocks_foreign_file() -> None:
    result = ToolRuntime().execute("table_tool", "analyze_table", {"query": "统计", "file_id": "file_other"}, _context())
    assert result.success is False
    assert result.error_code == "PERMISSION_DENIED"


def test_high_risk_action_requires_confirmation_and_rejection_blocks(monkeypatch) -> None:
    CONFIRMATION_STORE.clear()
    monkeypatch.setattr(AuditLogRepository, "record", lambda self, **kwargs: {"audit_id": "audit_confirmation", **kwargs})
    first = ToolRuntime().execute("file_tool", "delete", {"file_id": "file_ok"}, _context())
    assert first.success is True
    assert first.status == "confirmation_required"
    assert first.requires_confirmation is True
    assert first.error_code == "CONFIRMATION_REQUIRED"
    confirmation_id = first.confirmation_payload["confirmation_id"]
    update_confirmation_status(confirmation_id, "rejected")
    rejected = ToolRuntime().execute("file_tool", "delete", {"file_id": "file_ok", "confirmation_id": confirmation_id}, _context())
    assert rejected.success is False
    assert rejected.error_code == "CONFIRMATION_REJECTED"


def test_timeout_returns_tool_timeout(monkeypatch) -> None:
    runtime = _runtime_with_custom_tool(
        ActionSchema(
            action_name="run",
            description="slow",
            timeout_seconds=1,
            input_schema={"type": "object", "properties": {}},
            side_effects=["none"],
        )
    )
    monkeypatch.setattr(AuditLogRepository, "record", lambda self, **kwargs: {"audit_id": "audit_timeout", **kwargs})

    def slow_dispatch(*args, **kwargs):
        time.sleep(2)
        return ToolResult(True, "unit_tool", "run", summary="late")

    monkeypatch.setattr(runtime, "_dispatch", slow_dispatch)
    started = time.perf_counter()
    result = runtime.execute("unit_tool", "run", {}, _context())
    assert result.success is False
    assert result.error_code == "TOOL_TIMEOUT"
    assert time.perf_counter() - started < 1.8


def test_retry_policy_retries_then_succeeds(monkeypatch) -> None:
    runtime = _runtime_with_custom_tool(
        ActionSchema(
            action_name="run",
            description="flaky",
            input_schema={"type": "object", "properties": {}},
            retry_policy={"max_attempts": 2, "delay_seconds": 0},
            side_effects=["none"],
        )
    )
    monkeypatch.setattr(AuditLogRepository, "record", lambda self, **kwargs: {"audit_id": "audit_retry", **kwargs})
    calls = {"count": 0}

    def flaky_dispatch(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary")
        return ToolResult(True, "unit_tool", "run", summary="ok")

    monkeypatch.setattr(runtime, "_dispatch", flaky_dispatch)
    result = runtime.execute("unit_tool", "run", {}, _context())
    assert result.success is True
    assert calls["count"] == 2
    assert result.audit_id == "audit_retry"


def test_error_result_contains_diagnostics(monkeypatch) -> None:
    records = []

    def fake_record(self, **kwargs):
        records.append(kwargs)
        return {"audit_id": f"audit_{len(records)}"}

    monkeypatch.setattr(AuditLogRepository, "record", fake_record)
    result = ToolRuntime().execute("missing_tool", "run", {}, _context())
    assert result.error_code
    assert result.error_message
    assert result.elapsed_ms >= 0
    assert any(record["action"] == "tool.execute.error" for record in records)

