from __future__ import annotations

from .base import SQLiteRepository


class MessageRepository(SQLiteRepository):
    table_name = "messages"
    id_field = "message_id"

