"""Algorithm metadata and runtime result types."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable


AlgorithmCallable = Callable[[dict[str, Any], dict[str, Any]], "AlgorithmRunOutput"]


@dataclass(frozen=True)
class AlgorithmSpec:
    algorithm_id: str
    display_name: str
    category: str
    description: str
    input_type: str
    output_type: str
    default_params: dict[str, Any] = field(default_factory=dict)
    param_schema: dict[str, Any] = field(default_factory=dict)
    requires_model_file: bool = False
    model_file_key: str | None = None
    available: bool = True
    unavailable_reason: str = ""
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AlgorithmRunOutput:
    data: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    warning: str = ""


class RamanPipelineError(ValueError):
    """User-facing pipeline error."""

