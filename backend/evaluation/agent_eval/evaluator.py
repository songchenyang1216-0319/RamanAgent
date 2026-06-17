from __future__ import annotations

from typing import Any

from backend.agent.message_normalizer import MessageNormalizer
from backend.agent.intent_router import IntentRouter
from backend.agent.planner import Planner
from backend.agent.planning import LLMPlanner, ToolCatalog
from backend.agent.runtime.nodes.intent_node import should_use_legacy_rule

from .dataset_schema import AgentEvalCase, AgentEvalDataset
from .metrics import compute_agent_eval_metrics


class AgentEvaluator:
    def __init__(self) -> None:
        self.normalizer = MessageNormalizer()
        self.intent_router = IntentRouter()
        self.legacy_planner = Planner()
        self.llm_planner = LLMPlanner(use_external_model=False, mode="mock")
        self.catalog = ToolCatalog()

    def evaluate(self, dataset: AgentEvalDataset) -> dict[str, Any]:
        rows = [self.evaluate_case(case) for case in dataset.cases]
        return {
            "success": True,
            "dataset": dataset.source_path,
            "total": len(rows),
            "metrics": compute_agent_eval_metrics(rows),
            "cases": rows,
        }

    def evaluate_case(self, case: AgentEvalCase) -> dict[str, Any]:
        payload = {"message": case.message, **dict(case.metadata or {})}
        normalized = self.normalizer.normalize(payload)
        intent = self.intent_router.route(normalized)
        route = ""
        tool_name = ""
        algorithm_id = ""
        fallback = False
        error = False
        requires_file = False
        try:
            if should_use_legacy_rule(type("EvalState", (), {"normalized_message": normalized, "intent": intent})()):
                plan = self.legacy_planner.make_plan(normalized, intent)
                route = plan.route_type
                tool_name = plan.tool_name or plan.skill_name or ""
                fallback = route == "fallback"
                requires_file = bool(intent.requires_file)
            else:
                output = self.llm_planner.plan(normalized, self.catalog)
                route = output.plan.plan_type
                fallback = route == "fallback"
                requires_file = bool(output.plan.requires_file)
                if output.plan.steps:
                    first = output.plan.steps[0]
                    tool_name = first.tool_name
                    algorithm_id = self._algorithm_from_args(first.args)
        except Exception:
            error = True
        clarification = bool(requires_file and not normalized.has_file and route in {"raman_pipeline", "hybrid", "tool", "skill"})
        repair = False
        return {
            "case_id": case.case_id,
            "message": case.message,
            "expected_intent": case.expected_intent,
            "actual_intent": intent.intent,
            "intent_match": (not case.expected_intent) or intent.intent == case.expected_intent,
            "expected_route": case.expected_route,
            "actual_route": route,
            "route_match": (not case.expected_route) or route == case.expected_route,
            "expected_tool": case.expected_tool,
            "actual_tool": tool_name,
            "tool_match": (not case.expected_tool) or tool_name == case.expected_tool,
            "expected_algorithm": case.expected_algorithm,
            "actual_algorithm": algorithm_id,
            "algorithm_match": (not case.expected_algorithm) or algorithm_id == case.expected_algorithm,
            "fallback": fallback,
            "repair": repair,
            "clarification": clarification,
            "error": error,
        }

    def _algorithm_from_args(self, args: dict[str, Any]) -> str:
        steps = args.get("steps") if isinstance(args, dict) else None
        if isinstance(steps, list):
            for item in steps:
                if isinstance(item, dict) and item.get("algorithm_id"):
                    return str(item.get("algorithm_id"))
        if isinstance(args, dict) and args.get("template_id"):
            return f"template:{args.get('template_id')}"
        return ""
