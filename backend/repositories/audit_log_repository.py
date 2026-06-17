from __future__ import annotations

from typing import Any

from .base import SQLiteRepository, dumps_json


class AuditLogRepository(SQLiteRepository):
    table_name = "audit_logs"
    id_field = "audit_id"

    def record(
        self,
        *,
        user_id: str | None,
        action: str,
        resource_type: str | None = None,
        resource_id: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.create(
            {
                "user_id": user_id,
                "action": action,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "ip_address": ip_address,
                "user_agent": user_agent,
                "detail_json": dumps_json(detail or {}),
            }
        )

