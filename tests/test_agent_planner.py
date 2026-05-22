from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.agent.agent_planner import AgentPlanner
from backend.agent.agent_service import RamanAgentService


def _plan_tools(message: str) -> list[str]:
    return [step.tool for step in AgentPlanner().plan(message).steps]


def test_planner_analyze_and_report_steps():
    tools = _plan_tools("帮我分析这个样品，看看结果是否可信，然后生成报告")
    assert tools == ["predict_methanol", "professional_analysis", "generate_report"]


def test_planner_compare_history_step():
    tools = _plan_tools("分析这个 CSV，再和历史样品对比一下")
    assert tools == ["predict_methanol", "compare_history"]


def test_planner_model_and_history_steps():
    tools = _plan_tools("看看当前用的模型和历史记录")
    assert tools == ["get_current_model", "list_history"]


def test_planner_step_failure_is_reported_without_crashing():
    service = RamanAgentService()
    response = service.chat("帮我分析这个样品，然后生成报告")

    assert response["category"] == "plan"
    assert response["intent"] == "agent_plan"
    assert response["success"] is False
    assert "step_status" in response["data"]
    assert response["data"]["step_status"][0]["tool"] == "predict_methanol"
    assert response["data"]["step_status"][0]["success"] is False
    assert "需要上传 CSV" in response["data"]["step_status"][0]["message"]


if __name__ == "__main__":
    raise SystemExit("Run with pytest")
