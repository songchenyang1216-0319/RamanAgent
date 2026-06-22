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
        if intent.intent in {"conversation_rag", "knowledge_base_rag", "mixed_rag"}:
            rag_scope = {
                "conversation_rag": "conversation",
                "knowledge_base_rag": "knowledge_base",
                "mixed_rag": "mixed",
            }.get(intent.intent, normalized.rag_scope or "conversation")
            if normalized.rag_scope in {"conversation", "knowledge_base", "mixed"}:
                rag_scope = normalized.rag_scope
            return AgentPlan(
                route_type="rag",
                rag_scope=rag_scope,
                knowledge_base_ids=list(normalized.knowledge_base_ids or []),
                model_provider=normalized.provider_id,
                model_name=normalized.model_id,
                steps=[
                    "retrieve_conversation_files" if rag_scope in {"conversation", "mixed"} else "skip_conversation_files",
                    "retrieve_knowledge_base" if rag_scope in {"knowledge_base", "mixed"} else "skip_knowledge_base",
                    "call_model_with_citations",
                    "build_response",
                ],
            )

        if normalized.file_type == "image":
            image_action = self._infer_image_action(normalized.message)
            return AgentPlan(
                route_type="skill",
                skill_name="image-understanding",
                skill_mode="executable",
                action_name=image_action,
                steps=["run_image_skill", "build_response"],
            )

        uploaded_skill, _ = match_uploaded_skill(normalized.message, file_suffix=normalized.file_suffix)
        reserved_intents = {
            "csv_analysis",
            "document_processing",
            "file_conversion",
            "report_generation",
            "conversation_rag",
            "knowledge_base_rag",
            "mixed_rag",
            "raman_analysis",
        }
        if uploaded_skill is not None and intent.intent not in reserved_intents:
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

        if intent.intent == "web_search":
            return AgentPlan(
                route_type="skill",
                skill_name="web-search",
                skill_mode="executable",
                action_name="answer_with_sources",
                steps=["run_web_search_skill", "build_response"],
            )

        if intent.intent == "file_info":
            return AgentPlan(
                route_type="tool",
                tool_name="file_info_tool",
                steps=["read_file_metadata", "build_response"],
            )

        if intent.intent == "report_generation":
            return AgentPlan(
                route_type="skill",
                skill_name="report-generator",
                skill_mode="executable",
                action_name="generate_markdown",
                steps=["collect_workspace_context", "run_report_generator", "build_response"],
            )

        if intent.intent == "file_conversion":
            return AgentPlan(
                route_type="skill",
                skill_name="file-converter",
                skill_mode="executable",
                action_name="convert_file",
                steps=["validate_source_file", "convert_file", "build_response"],
            )

        if intent.intent in {"model_management", "skill_management", "unknown"}:
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
            if normalized.has_file:
                uploaded_doc_skill, _ = match_uploaded_skill(normalized.message, file_suffix=normalized.file_suffix)
                if uploaded_doc_skill is not None and uploaded_doc_skill.skill_mode == "prompt_only":
                    return AgentPlan(
                        route_type="skill",
                        skill_name=uploaded_doc_skill.name,
                        skill_mode=uploaded_doc_skill.skill_mode,
                        action_name="run_uploaded_skill",
                        steps=["run_skill", "build_response"],
                    )
                document_action = "summarize"
                if any(keyword in normalized.message for keyword in ("大纲", "目录", "结构")):
                    document_action = "outline"
                elif any(keyword in normalized.message for keyword in ("重点", "要点", "关键信息")):
                    document_action = "extract_key_points"
                elif any(keyword in normalized.message for keyword in ("翻译", "译成")):
                    document_action = "translate"
                elif any(keyword in normalized.message for keyword in ("润色", "改写")):
                    document_action = "polish"
                return AgentPlan(
                    route_type="skill",
                    skill_name="document-reader",
                    skill_mode="executable",
                    action_name=document_action,
                    steps=["retrieve_file_chunks", "run_document_reader", "build_response"],
                )
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
                route_type="model",
                tool_name=None,
                model_provider=normalized.provider_id,
                model_name=normalized.model_id,
                steps=["call_model", "build_response"],
            )

        if intent.intent == "code_analysis":
            return AgentPlan(
                route_type="skill",
                skill_name="code-assistant",
                skill_mode="executable",
                action_name="explain_code",
                steps=["read_code_file", "run_code_assistant", "build_response"],
            )

        if intent.intent == "image_understanding":
            return AgentPlan(
                route_type="skill",
                skill_name="image-understanding",
                skill_mode="executable",
                action_name="ocr_extract_text" if any(keyword in normalized.message for keyword in ("文字", "OCR", "提取", "识别")) else "classify_image_type",
                steps=["run_image_skill", "build_response"],
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
                    if self._is_generic_table_analysis_request(normalized.message):
                        return AgentPlan(
                            route_type="skill",
                            skill_name="table-analysis",
                            skill_mode="executable",
                            action_name="summarize_table",
                            steps=["run_data_analysis_skill", "build_response"],
                            debug={"table_query_plan": {"action": "summarize_table", "confidence": 0.85, "reason": "泛化表格追问默认返回概览"}},
                        )
                    query_plan = self.table_query_planner.plan(normalized.message, df)
                    if query_plan.action == "clarify" and self._is_generic_table_analysis_request(normalized.message):
                        return AgentPlan(
                            route_type="skill",
                            skill_name="table-analysis",
                            skill_mode="executable",
                            action_name="summarize_table",
                            steps=["run_data_analysis_skill", "build_response"],
                            debug={"table_query_plan": {"action": "summarize_table", "confidence": 0.8, "reason": "泛化表格分析请求默认返回概览"}},
                        )
                    if query_plan.action not in {"summarize_table", "clarify"}:
                        return AgentPlan(
                            route_type="skill",
                            skill_name="table-analysis",
                            skill_mode="executable",
                            action_name=query_plan.action,
                            steps=["run_data_analysis_skill", "build_response"],
                            debug={"table_query_plan": query_plan.to_dict()},
                        )
                    if query_plan.action == "summarize_table":
                        return AgentPlan(
                            route_type="skill",
                            skill_name="table-analysis",
                            skill_mode="executable",
                            action_name="summarize_table",
                            steps=["run_data_analysis_skill", "build_response"],
                            debug={"table_query_plan": query_plan.to_dict()},
                        )
                    if query_plan.action == "clarify":
                        return AgentPlan(
                            route_type="skill",
                            skill_name="table-analysis",
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

    def _is_generic_table_analysis_request(self, message: str) -> bool:
        text = str(message or "").strip().lower()
        if not text:
            return True
        generic_markers = (
            "分析这个csv",
            "分析这个 csv",
            "分析一下这个csv",
            "分析一下这个 csv",
            "分析这个文件",
            "分析一下这个文件",
            "看看这个csv",
            "看看这个 csv",
            "看看这个文件",
            "分析这个简介",
            "分析一下这个简介",
            "这个简介",
            "简介",
            "总结这个csv",
            "总结这个 csv",
            "总结这个文件",
            "主要内容",
            "内容是什么",
            "内容总结",
            "讲的是什么",
        )
        return any(marker in text for marker in generic_markers)

    def _infer_image_action(self, message: str) -> str:
        text = str(message or "")
        lowered = text.lower()
        if any(keyword in text for keyword in ("文字", "提取文字", "识别文字", "图片里的文字", "截图内容整理", "翻译图片")) or "ocr" in lowered:
            return "ocr_extract_text"
        if any(keyword in text for keyword in ("质量", "清晰", "模糊", "亮度", "对比度", "分辨率")):
            return "image_quality_check"
        if any(keyword in text for keyword in ("报错", "错误", "异常", "bug", "界面", "页面", "按钮", "截图", "前端", "后端", "ui")):
            return "analyze_screenshot"
        if any(keyword in text for keyword in ("图表", "曲线", "坐标轴", "柱状图", "折线图", "散点图", "论文图", "figure")):
            return "analyze_chart_or_figure"
        if any(keyword in lowered for keyword in ("raman", "sers")) or any(keyword in text for keyword in ("拉曼", "光谱", "谱图", "峰位", "峰强")):
            return "analyze_raman_spectrum_image"
        return "analyze_general_image"
