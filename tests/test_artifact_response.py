from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.agent.response_builder import ResponseBuilder
from backend.agent.types import AgentPlan, IntentResult, NormalizedMessage


def test_response_builder_promotes_artifacts_from_data():
    normalized = NormalizedMessage(message="生成报告", raw_message="生成报告", conversation_id="artifact-conv", session_id="artifact-conv", user_id="artifact-user")
    intent = IntentResult(intent="report_generation", confidence=0.9, reason="test", recommended_route="skill")
    plan = AgentPlan(route_type="skill", skill_name="report-generator", action_name="generate_markdown")
    payload = ResponseBuilder().build(
        {
            "success": True,
            "reply": "报告已生成。",
            "data": {"artifacts": [{"artifact_id": "a1", "type": "markdown", "title": "报告"}]},
        },
        normalized,
        intent,
        plan,
    )
    assert payload["artifacts"][0]["artifact_id"] == "a1"
    assert payload["skill_name"] == "report-generator"
    assert payload["skill_action"] == "generate_markdown"
