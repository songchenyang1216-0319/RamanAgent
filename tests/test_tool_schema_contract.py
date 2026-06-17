from __future__ import annotations

from backend.agent.planning.tool_catalog import ToolCatalog
from backend.agent.planning.tool_schema import DANGER_LEVELS, SIDE_EFFECTS


def test_tool_schema_contract() -> None:
    catalog = ToolCatalog()
    assert catalog.get("raman_pipeline") is not None
    risky_effects = {"execute_code", "delete_file", "modify_model", "cost_money"}
    danger_rank = {"safe": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
    for tool in catalog.to_prompt_payload():
        assert tool["source"]
        assert isinstance(tool["available"], bool)
        assert tool["danger_level"] in DANGER_LEVELS
        assert tool["input_schema"]["type"] == "object"
        for action in tool["actions"].values():
            assert action["input_schema"]["type"] == "object"
            assert action["output_schema"]["type"] == "object"
            assert action["danger_level"] in DANGER_LEVELS
            assert set(action["side_effects"]).issubset(SIDE_EFFECTS)
            if action["danger_level"] in {"high", "critical"}:
                assert action["requires_confirmation"] is True
            if risky_effects.intersection(action["side_effects"]):
                assert danger_rank[action["danger_level"]] >= danger_rank["medium"]
