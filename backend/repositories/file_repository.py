from __future__ import annotations

from .base import SQLiteRepository


class FileRepository(SQLiteRepository):
    table_name = "files"
    id_field = "file_id"

