from __future__ import annotations

from pathlib import Path

from backend.agent.types import AgentPlan, IntentResult, NormalizedMessage
from backend.skills.registry import get_skill, match_uploaded_skill
from backend.skills.table_query_planner import TableQueryPlanner
from backend.skills.data_analysis_skill import load_table_file


class Planner:
    def __init__(self) -> None:
        self.table_query_planner = TableQueryPlanner()

    def make_plan(self, normalized: NormalizedMessage, intent: IntentResult) -> AgentPlan:
        if normalized.file_type == "image":
            image_action = "ocr_extract_text" if any(keyword in normalized.message for keyword in ("文字", "OCR", "提取", "识别")) else "classify_image_type"
            return AgentPlan(
                route_type="skill",
                skill_name="image-router-skill",
                skill_mode="executable",
                action_name=image_action,
                steps=["run_image_skill", "build_response"],
            )

        uploaded_skill, _ = match_uploaded_skill(normalized.message, file_suffix=normalized.file_suffix)
        if uploaded_skill is not None and intent.intent not in {"csv_analysis", "raman_analysis"}:
            return AgentPlan(
                route_type="skill",
                skill_name=uploaded_skill.name,
                skill_mode=uploaded_skill.skill_mode,
                action_name="run_uploaded_skill",
                steps=["run_skill", "build_response"],
            )

        if intent.intent == "general_chat":
            return AgentPlan(
                route_type="model",
                model_provider=normalized.provider_id,
                model_name=normalized.model_id,
                steps=["call_model", "build_response"],
            )

        if intent.intent in {"model_management", "skill_management", "web_search", "unknown"}:
            return AgentPlan(
                route_type="fallback",
                steps=["legacy_fallback", "build_response"],
            )

        if intent.intent == "raman_analysis":
            if normalized.has_file:
                return AgentPlan(
                    route_type="hybrid",
                    skill_name="raman_spectroscopy_skill",
                    skill_mode="executable",
                    action_name="predict_methanol_concentration",
                    steps=["run_raman_skill_pipeline", "build_response"],
                )
            return AgentPlan(
                route_type="model",
                model_provider=normalized.provider_id,
                model_name=normalized.model_id,
                steps=["call_model", "build_response"],
            )

        if intent.intent == "document_processing":
            uploaded_skill, _ = match_uploaded_skill(normalized.message, file_suffix=normalized.file_suffix)
            if uploaded_skill is not None:
                return AgentPlan(
                    route_type="skill",
                    skill_name=uploaded_skill.name,
                    skill_mode=uploaded_skill.skill_mode,
                    action_name="run_uploaded_skill",
                    steps=["run_skill", "build_response"],
                )
            return AgentPlan(
                route_type="model" if not normalized.has_file else "tool",
                tool_name="document_tool" if normalized.has_file else None,
                model_provider=normalized.provider_id,
                model_name=normalized.model_id,
                steps=["extract_document", "call_model", "build_response"] if normalized.has_file else ["call_model", "build_response"],
            )

        if intent.intent == "csv_analysis":
            if normalized.has_file and normalized.file_path:
                lowered = normalized.message.lower()
                if any(keyword in normalized.message for keyword in ("列名", "基本统计", "describe")) and not any(
                    keyword in lowered for keyword in ("有多少条", "筛选", "每个", "group by", "groupby", "top", "排序", "等于", "=")
                ):
                    return AgentPlan(
                        route_type="tool",
                        tool_name="csv_tool",
                        steps=["run_csv_tool", "build_response"],
                    )
                try:
                    df = load_table_file(Path(normalized.file_path), preview_only=False).df
                    query_plan = self.table_query_planner.plan(normalized.message, df)
                    if query_plan.action not in {"summarize_table", "clarify"}:
                        return AgentPlan(
                            route_type="skill",
                            skill_name="data-analysis-skill",
                            skill_mode="executable",
                            action_name=query_plan.action,
                            steps=["run_data_analysis_skill", "build_response"],
                            debug={"table_query_plan": query_plan.to_dict()},
                        )
                    if query_plan.action == "summarize_table":
                        return AgentPlan(
                            route_type="skill",
                            skill_name="data-analysis-skill",
                            skill_mode="executable",
                            action_name="summarize_table",
                            steps=["run_data_analysis_skill", "build_response"],
                            debug={"table_query_plan": query_plan.to_dict()},
                        )
                    if query_plan.action == "clarify":
                        return AgentPlan(
                            route_type="skill",
                            skill_name="data-analysis-skill",
                            skill_mode="executable",
                            action_name="clarify",
                            steps=["run_data_analysis_skill", "build_response"],
                            debug={"table_query_plan": query_plan.to_dict()},
                        )
                    return AgentPlan(
                        route_type="tool",
                        tool_name="csv_tool",
                        steps=["run_csv_tool", "build_response"],
                    )
                except Exception as exc:
                    return AgentPlan(
                        route_type="tool",
                        tool_name="csv_tool",
                        steps=["run_csv_tool", "build_response"],
                        debug={"planner_error": str(exc)},
                    )
            return AgentPlan(
                route_type="tool",
                tool_name="csv_tool",
                steps=["run_csv_tool", "build_response"],
            )

        default_skill = get_skill("agent_system_skill")
        return AgentPlan(
            route_type="fallback",
            skill_name=default_skill.name if default_skill else None,
            steps=["legacy_fallback", "build_response"],
        )
