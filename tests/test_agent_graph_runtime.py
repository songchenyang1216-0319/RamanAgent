from __future__ import annotations

from pathlib import Path

import numpy as np

from backend.agent.orchestrator import AgentOrchestrator
from backend.agent.runtime.graph_runner import GraphRunner


def _write_mock_spectrum(path: Path) -> None:
    x = np.linspace(400, 1800, 121)
    y = 0.1 * np.sin(x / 55.0) + np.exp(-0.5 * ((x - 1000) / 40) ** 2) + 0.15
    path.write_text(
        "wavenumber,intensity\n" + "\n".join(f"{float(a)},{float(b)}" for a, b in zip(x, y)),
        encoding="utf-8",
    )


def test_graph_runner_runs_general_chat(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_RUNTIME_MODE", "graph")
    response = GraphRunner().run({"message": "你好", "debug": True})
    assert response["success"] is True
    assert response["reply"]
    assert response["debug"]["node_trace"]


def test_graph_runner_runs_raman_pipeline_mock_plan(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LLM_PLANNER_MODE", "mock")
    path = tmp_path / "spectrum.csv"
    _write_mock_spectrum(path)
    response = GraphRunner().run(
        {
            "message": "用 SG 平滑 + ALS 去基线 + z-score 归一化处理这个光谱",
            "file_path": str(path),
            "debug": True,
            "explicit_has_file": True,
        }
    )
    assert response["success"] is True
    assert response["route"] == "raman_pipeline"
    assert response["debug"]["validated_plan"]["valid"] is True


def test_orchestrator_hybrid_falls_back_when_graph_fails(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_RUNTIME_MODE", "hybrid")

    def boom(self, request_payload):
        raise RuntimeError("graph boom")

    monkeypatch.setattr("backend.agent.orchestrator.GraphRunner.run", boom)
    monkeypatch.setattr(
        AgentOrchestrator,
        "_handle_chat_legacy",
        lambda self, payload: {"success": True, "reply": "legacy ok", "intent": "general_chat", "route": "model", "debug": {}},
    )
    response = AgentOrchestrator().handle_chat({"message": "你好"})
    assert response["success"] is True
    assert response["reply"] == "legacy ok"
