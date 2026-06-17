from __future__ import annotations

from backend.repositories.audit_log_repository import AuditLogRepository
from backend.tool_runtime import ToolContext, ToolRuntime
from backend.tool_runtime.tool_confirmation import CONFIRMATION_STORE, update_confirmation_status


def test_tool_runtime_requires_confirmation_for_high_risk_action(monkeypatch) -> None:
    CONFIRMATION_STORE.clear()
    monkeypatch.setattr(AuditLogRepository, "record", lambda self, **kwargs: {"audit_id": "audit_1", **kwargs})
    context = ToolContext(user_id="u1", file_ids=["file_1"], metadata={"role": "admin"}, permissions=["*"])
    result = ToolRuntime().execute("file_tool", "delete", {"file_id": "file_1"}, context)
    assert result.success is True
    assert result.requires_confirmation is True
    assert result.error_code == "CONFIRMATION_REQUIRED"
    assert result.confirmation_payload["tool_name"] == "file_tool"


def test_tool_runtime_rejects_rejected_confirmation(monkeypatch) -> None:
    CONFIRMATION_STORE.clear()
    monkeypatch.setattr(AuditLogRepository, "record", lambda self, **kwargs: {"audit_id": "audit_1", **kwargs})
    context = ToolContext(user_id="u1", file_ids=["file_1"], metadata={"role": "admin"}, permissions=["*"])
    first = ToolRuntime().execute("file_tool", "delete", {"file_id": "file_1"}, context)
    confirmation_id = first.confirmation_payload["confirmation_id"]
    update_confirmation_status(confirmation_id, "rejected")
    result = ToolRuntime().execute("file_tool", "delete", {"file_id": "file_1", "confirmation_id": confirmation_id}, context)
    assert result.success is False
    assert result.error_code == "CONFIRMATION_REJECTED"
