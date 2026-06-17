from __future__ import annotations

from .base import SQLiteRepository


class ConversationRepository(SQLiteRepository):
    table_name = "conversations"
    id_field = "conversation_id"

