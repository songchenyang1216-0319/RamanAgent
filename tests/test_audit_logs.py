from __future__ import annotations

from backend.repositories.audit_log_repository import AuditLogRepository
from backend.tool_runtime import ToolContext, ToolRuntime
from backend.tool_runtime.adapters.builtin_tool_adapter import BuiltinToolAdapter
from backend.tool_runtime.tool_audit import sanitize_detail
from backend.tool_runtime.tool_result import ToolResult


def test_audit_detail_is_sanitized() -> None:
    sanitized = sanitize_detail({"api_key": "secret-value", "nested": {"token": "abc"}, "ok": "visible"})
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["nested"]["token"] == "[REDACTED]"
    assert sanitized["ok"] == "visible"


def test_tool_runtime_records_start_and_finish_audit(monkeypatch) -> None:
    records = []

    def fake_record(self, **kwargs):
        records.append(kwargs)
        return {"audit_id": f"audit_{len(records)}"}

    monkeypatch.setattr(AuditLogRepository, "record", fake_record)
    monkeypatch.setattr(
        BuiltinToolAdapter,
        "execute",
        lambda self, tool_name, action_name, args, context: ToolResult(True, tool_name, action_name, summary="ok"),
    )
    context = ToolContext(user_id="u1", metadata={"role": "admin"}, permissions=["*"])
    result = ToolRuntime().execute("model_tool", "list_models", {"api_key": "secret-value"}, context)
    assert result.success is True
    actions = [record["action"] for record in records]
    assert "tool.execute.start" in actions
    assert "tool.execute.finish" in actions
    start_record = next(record for record in records if record["action"] == "tool.execute.start")
    assert start_record["detail"]["args"]["api_key"] == "[REDACTED]"
