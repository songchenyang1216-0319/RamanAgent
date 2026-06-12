from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class KnowledgeBase:
    knowledge_base_id: str
    owner_user_id: str
    name: str
    description: str = ""
    visibility: str = "private"
    enabled: bool = True
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class KnowledgeBaseFile:
    kb_file_id: str
    knowledge_base_id: str
    owner_user_id: str
    original_filename: str
    stored_path: str
    file_type: str = ""
    mime_type: str = ""
    size: int = 0
    processing_status: str = "pending"
    rag_index_status: str = "pending"
    rag_index_error: str | None = None
    chunk_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
