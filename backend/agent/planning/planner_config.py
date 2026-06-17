from __future__ import annotations

import os
from dataclasses import dataclass


VALID_PLANNER_MODES = {"off", "mock", "llm", "hybrid"}


@dataclass(frozen=True)
class PlannerConfig:
    mode: str = "hybrid"

    @classmethod
    def from_env(cls) -> "PlannerConfig":
        raw = str(os.getenv("LLM_PLANNER_MODE", "hybrid") or "hybrid").strip().lower()
        mode = raw if raw in VALID_PLANNER_MODES else "hybrid"
        return cls(mode=mode)

    @property
    def external_required(self) -> bool:
        return self.mode == "llm"

    @property
    def external_allowed(self) -> bool:
        return self.mode in {"llm", "hybrid"}

    @property
    def mock_allowed(self) -> bool:
        return self.mode in {"mock", "hybrid"}

    @property
    def disabled(self) -> bool:
        return self.mode == "off"

