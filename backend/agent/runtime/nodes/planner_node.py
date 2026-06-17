from __future__ import annotations

from backend.agent.planner import Planner
from backend.agent.planning import LLMPlanner, ToolCatalog
from backend.agent.runtime.graph_node import GraphNode
from backend.agent.runtime.graph_state import GraphState
from backend.agent.runtime.nodes.intent_node import should_use_legacy_rule


class PlannerNode(GraphNode):
    name = "planner"
    status_text = "正在生成计划。"

    def __init__(
        self,
        *,
        legacy_planner: Planner | None = None,
        llm_planner: LLMPlanner | None = None,
        tool_catalog: ToolCatalog | None = None,
    ) -> None:
        self.legacy_planner = legacy_planner or Planner()
        self.tool_catalog = tool_catalog or ToolCatalog()
        self.llm_planner = llm_planner or LLMPlanner()

    def run(self, state: GraphState) -> GraphState:
        if state.observations.get("status") == "handled":
            return state
        normalized = state.normalized_message
        intent = state.intent
        if not normalized or not intent:
            state.should_fallback = True
            state.fallback_reason = "缺少 normalized_message 或 intent，无法规划。"
            return state

        if should_use_legacy_rule(state) or self.llm_planner.config.disabled:
            state.plan = self.legacy_planner.make_plan(normalized, intent)
            state.debug["planner_source"] = "legacy"
            return state

        output = self.llm_planner.plan(normalized, self.tool_catalog)
        state.planner_output = output
        state.plan = output.plan
        state.debug["planner_source"] = output.source
        state.debug["llm_plan_raw"] = output.raw
        if output.plan.plan_type == "fallback" or not output.plan.steps:
            state.plan = self.legacy_planner.make_plan(normalized, intent)
            state.debug["planner_source"] = f"{output.source}:legacy_fallback"
            state.debug["fallback_reason"] = output.plan.reason
        return state

    def end_summary(self, state: GraphState) -> str:
        plan = state.plan
        source = state.debug.get("planner_source") or "unknown"
        plan_type = getattr(plan, "plan_type", None) or getattr(plan, "route_type", None) or "fallback"
        return f"计划生成完成：{plan_type}（{source}）。"

    def trace_data(self, state: GraphState) -> dict:
        plan = state.plan
        payload = {"planner_source": state.debug.get("planner_source")}
        if hasattr(plan, "to_dict"):
            payload["plan"] = plan.to_dict()
        return payload
