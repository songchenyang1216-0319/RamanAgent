from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RAGEvalItem:
    query: str
    expected_answer_contains: list[str] = field(default_factory=list)
    expected_source_ids: list[str] = field(default_factory=list)
    should_answer: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

