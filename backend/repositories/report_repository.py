from __future__ import annotations

from .base import SQLiteRepository


class ReportRepository(SQLiteRepository):
    table_name = "reports"
    id_field = "report_id"

