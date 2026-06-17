from __future__ import annotations

from backend.agent.runtime.graph_runner import GraphRunner


def test_graph_runner_stream_contains_required_events(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_RUNTIME_MODE", "graph")
    events = list(GraphRunner().run_stream({"message": "你好"}))
    names = [event.event for event in events]
    assert "start" in names
    assert "status" in names
    assert "final" in names
    assert names[-1] == "done"
