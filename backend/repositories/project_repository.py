from __future__ import annotations

from .base import SQLiteRepository


class ProjectRepository(SQLiteRepository):
    table_name = "projects"
    id_field = "project_id"

