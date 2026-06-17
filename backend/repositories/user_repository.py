from __future__ import annotations

from .base import SQLiteRepository


class UserRepository(SQLiteRepository):
    table_name = "users"
    id_field = "user_id"

