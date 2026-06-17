from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AgentEvalCase:
    case_id: str
    message: str
    expected_intent: str = ""
    expected_route: str = ""
    expected_tool: str = ""
    expected_algorithm: str = ""
    expect_fallback: bool | None = None
    expect_repair: bool | None = None
    expect_clarification: bool | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentEvalDataset:
    cases: list[AgentEvalCase]
    source_path: str = ""


def load_agent_eval_dataset(path: str | Path) -> AgentEvalDataset:
    dataset_path = Path(path)
    payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    raw_cases = payload.get("cases") if isinstance(payload, dict) else payload
    cases = []
    for index, item in enumerate(raw_cases or [], start=1):
        if not isinstance(item, dict):
            continue
        cases.append(
            AgentEvalCase(
                case_id=str(item.get("case_id") or f"case_{index:03d}"),
                message=str(item.get("message") or ""),
                expected_intent=str(item.get("expected_intent") or ""),
                expected_route=str(item.get("expected_route") or ""),
                expected_tool=str(item.get("expected_tool") or ""),
                expected_algorithm=str(item.get("expected_algorithm") or ""),
                expect_fallback=item.get("expect_fallback"),
                expect_repair=item.get("expect_repair"),
                expect_clarification=item.get("expect_clarification"),
                metadata=dict(item.get("metadata") or {}),
            )
        )
    return AgentEvalDataset(cases=cases, source_path=str(dataset_path))
