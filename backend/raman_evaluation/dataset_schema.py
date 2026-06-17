from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RamanDataset:
    dataset_id: str
    name: str
    description: str = ""
    sample_count: int = 0
    target_type: str = "regression"
    target_name: str = "methanol"
    files: list[str] = field(default_factory=list)
    labels: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

