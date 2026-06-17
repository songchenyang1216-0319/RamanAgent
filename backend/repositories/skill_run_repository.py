from __future__ import annotations

from .base import SQLiteRepository


class SkillRunRepository(SQLiteRepository):
    table_name = "skill_runs"
    id_field = "skill_run_id"

