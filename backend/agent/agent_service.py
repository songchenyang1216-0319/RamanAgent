"""RamanAgent 工具调用服务。"""

from __future__ import annotations

import logging

from backend.agent.agent_planner import AgentPlan, AgentPlanner
from backend.agent.llm_intent_classifier import LLMIntentClassifier
from backend.agent.intent_router import detect_intent
from backend.agent.session_store import get_last_analysis, update_session
from backend.agent.tool_registry import get_tool_spec, list_tool_specs
from backend.agent.prompts.general_chat_prompt import build_general_chat_local_reply
from backend.services.history_service import list_analysis_history
from backend.services.llm_service import LLMService


logger = logging.getLogger(__name__)


class RamanAgentService:
    """基于规则路由的轻量级 Agent 服务。"""

    def __init__(self) -> None:
        self._llm_intent_classifier: LLMIntentClassifier | None = None
        self._planner = AgentPlanner()

    def list_tools(self) -> list[dict]:
        """列出当前可用工具。"""
        return list_tool_specs()

    def _tool_names(self) -> list[str]:
        """返回简化后的工具名列表。"""
        return [item["name"] for item in self.list_tools()]

    def _contains_any(self, text: str, keywords: tuple[str, ...]) -> bool:
        """检查文本是否命中任意关键词。"""
        return any(keyword in text for keyword in keywords)

    def _get_llm_intent_classifier(self) -> LLMIntentClassifier:
        """延迟初始化 LLM 意图分类器。"""
        if self._llm_intent_classifier is None:
            self._llm_intent_classifier = LLMIntentClassifier()
        return self._llm_intent_classifier

    def _current_model_version(self) -> str | None:
        """尽量拿到当前模型版本，用于对话上下文。"""
        response = self.run_tool("get_current_model", {})
        if not response.get("success"):
            return None
        data = response.get("data", {}) or {}
        return data.get("model_version")

    def _simplify_history_item(self, item: dict) -> dict:
        """压缩历史/实验记录条目，避免聊天响应过大。"""
        if not isinstance(item, dict):
            return {}
        return {
            "task_id": item.get("task_id"),
            "sample_file": item.get("sample_file") or item.get("sample_name"),
            "final_prediction": item.get("fusion_prediction"),
            "created_at": item.get("created_at"),
            "model_version": item.get("model_version"),
        }

    def _context_reference_type(self, message: str) -> str | None:
        """识别是否在引用本轮会话中的最近一次分析结果。"""
        text = (message or "").strip()
        lowered = text.lower()

        if self._contains_any(text, ("刚才的预测浓度", "刚才预测浓度", "刚才的预测值", "刚才那个样品浓度", "刚才结果多少", "刚才的预测结果是多少", "刚才的浓度是多少")):
            return "last_prediction"
        if self._contains_any(text, ("给我生成刚才的报告", "生成刚才的报告", "刚才的报告", "给我出刚才的报告", "给刚才那个样品生成报告")):
            return "report_generation"
        if self._contains_any(text, ("和历史样品比一下", "和之前的样品比一下", "跟历史样品比一下", "和历史记录比一下", "和之前样品比一下")):
            return "compare_history"
        if self._contains_any(text, ("这个结果靠谱吗", "刚才那个样品怎么样", "刚才那个结果怎么样", "这个结果怎么样", "刚才这个样品靠谱吗")):
            return "last_analysis_explanation"
        if "报告" in text and ("刚才" in text or "这个结果" in text or "这个样品" in text):
            return "report_generation"
        if "历史样品" in text and ("比" in text or "对比" in text):
            return "compare_history"
        if "浓度" in text and ("刚才" in text or "这个样品" in text or "这个结果" in text):
            return "last_prediction"
        if ("结果" in text or "样品" in text) and self._contains_any(text, ("靠谱吗", "怎么样", "如何")):
            return "last_analysis_explanation"
        if lowered in {"生成报告", "出报告"}:
            return "report_generation"
        return None

    def _missing_last_analysis_response(self, session_id: str | None, debug: bool = False) -> dict:
        """当会话中没有最近一次分析结果时返回自然提示。"""
        return self._build_response(
            intent="context_missing_analysis",
            category="general_chat",
            reply="我还没有看到你本轮会话中的分析结果，你可以先上传一个 CSV 光谱文件。",
            next_action="你可以直接使用 /api/agent/analyze-file 上传 Raman CSV 文件，我会把结果记在这轮会话里。",
            tool_used=None,
            tool_result=None,
            debug=debug,
            data=None,
            session_id=session_id,
        )

    def _build_last_prediction_response(self, last_analysis: dict, session_id: str | None, debug: bool = False) -> dict:
        """基于最近一次分析结果回答预测浓度。"""
        result = last_analysis.get("result", {}) or {}
        final_prediction = result.get("final_prediction")
        unit = result.get("unit", "") or ""
        sample_file = result.get("sample_file") or "刚才那个样品"
        reply = f"{sample_file} 的最近一次融合预测值是 {float(final_prediction):.4f}{unit}。"
        return self._build_response(
            intent="last_prediction",
            category="tool",
            reply=reply,
            next_action="如果你愿意，我也可以继续解释这个结果是否可靠，或者帮你和历史样品做对比。",
            tool_used="session_last_analysis",
            tool_result=None,
            debug=debug,
            data={
                "sample_file": result.get("sample_file"),
                "final_prediction": final_prediction,
                "svr_prediction": result.get("svr_prediction"),
                "rf_prediction": result.get("rf_prediction"),
                "unit": unit,
            },
            session_id=session_id,
        )

    def _build_last_analysis_explanation_response(self, last_analysis: dict, session_id: str | None, debug: bool = False) -> dict:
        """基于最近一次分析结果回答结果解释。"""
        explanation = str(last_analysis.get("llm_explanation") or "").strip()
        if not explanation:
            explain_result = self.run_tool(
                "explain_result",
                {
                    "result": last_analysis.get("result", {}) or {},
                    "professional_analysis": last_analysis.get("professional_analysis", {}) or {},
                    "model_info": last_analysis.get("model_info", {}) or {},
                    "experiment_metadata": last_analysis.get("experiment_metadata", {}) or {},
                },
            )
            explanation = explain_result.get("explanation", "") or "我已经拿到刚才那次分析结果，但当前还没有更多解释内容。"
            updated_last_analysis = dict(last_analysis)
            updated_last_analysis["llm_explanation"] = explanation
            if session_id:
                update_session(session_id, "last_analysis", updated_last_analysis)
        return self._build_response(
            intent="explain_result",
            category="tool",
            reply=explanation,
            next_action="如果你想继续，我也可以直接给你生成报告，或者和历史样品做相似性对比。",
            tool_used="explain_result",
            tool_result=None,
            debug=debug,
            data={"explanation": explanation},
            session_id=session_id,
        )

    def _build_context_report_response(self, last_analysis: dict, session_id: str | None, debug: bool = False) -> dict:
        """基于最近一次分析结果生成或返回报告。"""
        report = last_analysis.get("report")
        if not report:
            report_result = self.run_tool(
                "generate_report",
                {
                    "result": last_analysis.get("result", {}) or {},
                    "llm_explanation": last_analysis.get("llm_explanation"),
                    "professional_analysis": last_analysis.get("professional_analysis", {}) or {},
                    "model_info": last_analysis.get("model_info", {}) or {},
                    "experiment_metadata": last_analysis.get("experiment_metadata", {}) or {},
                },
            )
            if report_result.get("success"):
                report = {
                    "report_path": report_result.get("report_path"),
                    "report_file": report_result.get("report_file"),
                }
                updated_last_analysis = dict(last_analysis)
                updated_last_analysis["report"] = report
                if session_id:
                    update_session(session_id, "last_analysis", updated_last_analysis)
                    update_session(session_id, "last_report", report)
            else:
                return self._build_response(
                    intent="generate_report",
                    category="tool",
                    reply=report_result.get("error_message", "报告生成失败。"),
                    next_action="你可以先确认最近一次分析结果是否完整，或者重新上传 CSV 文件。",
                    tool_used="generate_report",
                    tool_result=None,
                    debug=debug,
                    success=False,
                    error_message=report_result.get("error_message"),
                    data=None,
                    session_id=session_id,
                )

        report_file = (report or {}).get("report_file") or "最近一次报告"
        return self._build_response(
            intent="generate_report",
            category="tool",
            reply=f"刚才那次分析的报告已经准备好了，当前报告文件是 {report_file}。",
            next_action="如果你还想继续，我也可以解释这个结果，或者帮你和历史样品做对比。",
            tool_used="generate_report",
            tool_result=None,
            debug=debug,
            data=report,
            session_id=session_id,
        )

    def _build_context_compare_response(self, last_analysis: dict, session_id: str | None, debug: bool = False) -> dict:
        """基于最近一次分析结果做历史相似样品对比。"""
        compare_result = self.run_tool(
            "find_similar_history",
            {
                "current_prediction_result": last_analysis.get("result", {}) or {},
            },
        )
        success = bool(compare_result.get("success"))
        return self._build_response(
            intent="find_similar_history",
            category="tool",
            reply=compare_result.get("message", "历史相似样品对比已完成。"),
            next_action="如果你想继续，我也可以帮你解释刚才那次结果，或者生成对应报告。",
            tool_used="find_similar_history",
            tool_result=None,
            debug=debug,
            success=success,
            error_message=None if success else compare_result.get("message"),
            data={
                "similar_records": compare_result.get("similar_records", []) or [],
                "message": compare_result.get("message"),
            },
            session_id=session_id,
        )

    def _handle_session_context_request(self, message: str, session_id: str | None, debug: bool = False) -> dict | None:
        """优先处理引用本轮最近一次分析结果的提问。"""
        if not session_id:
            return None

        context_type = self._context_reference_type(message)
        if context_type is None:
            return None

        last_analysis = get_last_analysis(session_id)
        if not last_analysis:
            return self._missing_last_analysis_response(session_id, debug=debug)

        if context_type == "last_prediction":
            return self._build_last_prediction_response(last_analysis, session_id, debug=debug)
        if context_type == "last_analysis_explanation":
            return self._build_last_analysis_explanation_response(last_analysis, session_id, debug=debug)
        if context_type == "report_generation":
            return self._build_context_report_response(last_analysis, session_id, debug=debug)
        if context_type == "compare_history":
            return self._build_context_compare_response(last_analysis, session_id, debug=debug)
        return None

    def _run_plan_tool_step(self, tool: str, params: dict, context: dict) -> dict:
        """执行单个 plan 步骤，并把必要结果写入上下文。"""
        last_analysis = context.get("last_analysis") or {}
        result = context.get("result") or (last_analysis.get("result") if isinstance(last_analysis, dict) else None)
        csv_path = params.get("csv_path") or params.get("file_path") or (last_analysis.get("saved_file") if isinstance(last_analysis, dict) else None)

        if tool == "get_current_model":
            output = self.run_tool("get_current_model", {})
            if output.get("success"):
                context["model_info"] = output.get("data", {}) or {}
            return output

        if tool == "list_history":
            output = self.run_tool("list_history", {"limit": params.get("limit", 10)})
            if output.get("success"):
                context["history"] = output
            return output

        if tool == "predict_methanol":
            file_path = params.get("file_path")
            if not file_path:
                return {"success": False, "error_message": "需要上传 CSV 文件后才能执行样品分析。"}
            output = self.run_tool("predict_methanol", {"file_path": file_path, "debug": False})
            if output.get("success"):
                context["result"] = output.get("result", {}) or {}
                context["figure_paths"] = output.get("figure_paths", {}) or {}
            return output

        if tool == "spectral_quality":
            if not csv_path:
                return {"success": False, "error_message": "需要先上传 CSV 文件，才能评估光谱质量。"}
            output = self.run_tool("analyze_spectrum_quality", {"csv_path": csv_path})
            if output.get("success"):
                context["quality_analysis"] = output
            return output

        if tool == "peak_analysis":
            if not csv_path:
                return {"success": False, "error_message": "需要先上传 CSV 文件，才能识别峰位。"}
            output = self.run_tool("detect_peaks", {"csv_path": csv_path})
            if output.get("success"):
                context["peak_analysis"] = output
            return output

        if tool == "professional_analysis":
            if csv_path and result:
                output = self.run_tool("professional_spectral_analysis", {"csv_path": csv_path, "prediction_result": result})
                if output.get("success"):
                    context["professional_analysis"] = output
                return output
            if result:
                output = self.run_tool(
                    "explain_result",
                    {
                        "result": result,
                        "professional_analysis": context.get("professional_analysis", {}),
                        "model_info": context.get("model_info", {}),
                        "experiment_metadata": context.get("experiment_metadata", {}),
                    },
                )
                if output.get("success") or output.get("explanation"):
                    context["explanation"] = output.get("explanation")
                return output
            return {"success": False, "error_message": "需要先有预测结果，才能输出专业解释。"}

        if tool == "compare_history":
            if not result:
                return {"success": False, "error_message": "需要先有当前样品的预测结果，才能和历史样品对比。"}
            output = self.run_tool("find_similar_history", {"current_prediction_result": result})
            if output.get("success"):
                context["similarity_analysis"] = output
            return output

        if tool == "generate_report":
            if not result:
                return {"success": False, "error_message": "需要先有有效分析结果，才能生成报告。"}
            output = self.run_tool(
                "generate_report",
                {
                    "result": result,
                    "llm_explanation": context.get("explanation") or (last_analysis.get("llm_explanation") if isinstance(last_analysis, dict) else None),
                    "professional_analysis": context.get("professional_analysis") or (last_analysis.get("professional_analysis", {}) if isinstance(last_analysis, dict) else {}),
                    "model_info": context.get("model_info") or (last_analysis.get("model_info", {}) if isinstance(last_analysis, dict) else {}),
                    "experiment_metadata": context.get("experiment_metadata") or (last_analysis.get("experiment_metadata", {}) if isinstance(last_analysis, dict) else {}),
                },
            )
            if output.get("success"):
                context["report"] = {"report_path": output.get("report_path"), "report_file": output.get("report_file")}
            return output

        if tool == "general_chat":
            return {"success": True, "reply": "我可以继续聊，也可以帮你拆解 Raman 分析任务。"}

        return {"success": False, "error_message": f"Planner 暂不支持步骤: {tool}"}

    def _slim_plan_data(self, context: dict, step_status: list[dict]) -> dict:
        """压缩 plan 执行结果，避免把内部大对象直接暴露给前端。"""
        result = context.get("result") or {}
        professional = context.get("professional_analysis") or {}
        summary = professional.get("professional_summary", {}) if isinstance(professional, dict) else {}
        report = context.get("report") or {}
        model_info = context.get("model_info") or {}
        similarity = context.get("similarity_analysis") or {}

        key_findings = []
        if result.get("final_prediction") is not None:
            key_findings.append(f"融合预测值为 {float(result.get('final_prediction')):.4f}{result.get('unit', '') or ''}")
        key_findings.extend(summary.get("key_findings", []) or [])
        if similarity.get("message"):
            key_findings.append(similarity["message"])
        if model_info.get("model_version"):
            key_findings.append(f"当前模型版本为 {model_info.get('model_version')}")

        figure_paths = result.get("figure_paths") or context.get("figure_paths") or {}
        return {
            "summary": "复合任务已执行完成。" if any(item["success"] for item in step_status) else "复合任务未能完成。",
            "key_findings": list(dict.fromkeys(key_findings))[:8],
            "confidence": result.get("confidence", {}) or {},
            "report_url": report.get("report_path"),
            "figure_urls": figure_paths,
            "step_status": step_status,
        }

    def _build_plan_reply(self, data: dict) -> str:
        """生成面向用户的计划执行摘要。"""
        succeeded = [item for item in data["step_status"] if item["success"]]
        failed = [item for item in data["step_status"] if not item["success"]]
        parts = [f"我按计划执行了 {len(data['step_status'])} 个步骤，其中 {len(succeeded)} 个成功。"]
        if data["key_findings"]:
            parts.append("关键发现：" + "；".join(data["key_findings"][:3]) + "。")
        if data.get("report_url"):
            parts.append(f"报告已生成：{data['report_url']}。")
        if failed:
            parts.append("有些步骤还需要补充输入：" + "；".join(f"{item['tool']}：{item['message']}" for item in failed[:3]) + "。")
        return "".join(parts)

    def _execute_agent_plan(
        self,
        plan: AgentPlan,
        message: str,
        params: dict | None = None,
        debug: bool = False,
        session_id: str | None = None,
    ) -> dict:
        """按顺序执行 AgentPlan，并返回瘦身后的结果。"""
        context = {"last_analysis": get_last_analysis(session_id) if session_id else None}
        params = params or {}
        step_status = []

        for step in plan.steps:
            try:
                output = self._run_plan_tool_step(step.tool, params, context)
                success = bool(output.get("success"))
                message_text = output.get("message") or output.get("error_message") or output.get("reply") or "步骤执行完成。"
            except Exception as exc:
                logger.exception("Agent plan step failed: %s", step.tool)
                success = False
                message_text = str(exc)
            step_status.append(
                {
                    "tool": step.tool,
                    "reason": step.reason,
                    "success": success,
                    "message": message_text,
                }
            )

        data = self._slim_plan_data(context, step_status)
        return self._build_response(
            intent="agent_plan",
            category="plan",
            reply=self._build_plan_reply(data),
            next_action="你可以继续追问某一步的细节，或者补充 CSV 文件后让我继续执行未完成的步骤。",
            tool_used="agent_planner",
            tool_result=plan.to_dict() if debug else None,
            raw_intent={"intent": "agent_plan", "category": "plan", "message": message},
            debug=debug,
            success=any(item["success"] for item in step_status),
            data=data,
            session_id=session_id,
        )

    def _compact_data(self, intent: str, tool_result: dict, params: dict | None = None) -> dict | None:
        """把工具结果压缩成聊天接口需要的核心数据。"""
        params = params or {}
        if not isinstance(tool_result, dict):
            return None

        if intent == "get_current_model":
            data = tool_result.get("data", {}) or {}
            training_data = data.get("training_data", {}) or {}
            return {
                "model_version": data.get("model_version"),
                "model_name": data.get("model_name"),
                "target": data.get("target"),
                "unit": data.get("unit"),
                "algorithm": data.get("algorithm", []),
                "training_data": {
                    "sample_count": training_data.get("sample_count"),
                    "concentration_range": training_data.get("concentration_range"),
                },
            }

        if intent == "check_current_model":
            data = tool_result.get("data", {}) or {}
            missing_files = data.get("missing_files", []) or []
            existing_files = data.get("existing_files", []) or []
            return {
                "success": bool(tool_result.get("success")),
                "missing_files": missing_files,
                "existing_count": len(existing_files),
                "missing_count": len(missing_files),
                "message": "当前模型文件检查完成，模型可用。" if not missing_files else "当前模型文件检查完成，但存在缺失文件。",
            }

        if intent in {"list_history", "get_experiment_history"}:
            items = tool_result.get("items", []) or []
            return {
                "total": tool_result.get("total", len(items)),
                "items": [self._simplify_history_item(item) for item in items[:5]],
            }

        if intent in {"get_history_detail", "get_experiment_detail"}:
            item = tool_result.get("item") or tool_result.get("data") or {}
            return self._simplify_history_item(item)

        if intent == "predict_methanol":
            return {
                "final_prediction": tool_result.get("final_prediction"),
                "svr_prediction": tool_result.get("svr_prediction"),
                "rf_prediction": tool_result.get("rf_prediction"),
                "model_disagreement": tool_result.get("model_disagreement", {}) or {},
                "confidence": tool_result.get("confidence", {}) or {},
                "figure_paths": tool_result.get("figure_paths", {}) or {},
                "warnings": tool_result.get("warnings", []) or [],
            }

        if intent == "generate_report":
            return {
                "report_path": tool_result.get("report_path"),
                "report_file": tool_result.get("report_file"),
            }

        if intent == "explain_result":
            return {"explanation": tool_result.get("explanation")}

        if intent == "professional_spectral_analysis":
            return {
                "peak_analysis": tool_result.get("peak_analysis", {}) or {},
                "quality_analysis": tool_result.get("quality_analysis", {}) or {},
                "baseline_analysis": tool_result.get("baseline_analysis", {}) or {},
                "similarity_analysis": tool_result.get("similarity_analysis", {}) or {},
                "professional_summary": tool_result.get("professional_summary", {}) or {},
            }

        if intent == "find_similar_history":
            return {
                "similar_records": tool_result.get("similar_records", []) or [],
                "message": tool_result.get("message"),
            }

        if intent == "check_artifacts":
            return {
                "success": bool(tool_result.get("success")),
                "missing_files": tool_result.get("missing_files", []) or [],
                "existing_count": len(tool_result.get("existing_files", []) or []),
                "missing_count": len(tool_result.get("missing_files", []) or []),
                "message": "模型文件检查完成。" if tool_result.get("success") else "模型文件检查完成，但存在缺失文件。",
            }

        if intent == "list_model_versions":
            data = tool_result.get("data", []) or []
            return {
                "models": [
                    {
                        "model_version": item.get("model_version"),
                        "model_name": item.get("model_name"),
                        "target": item.get("target"),
                    }
                    for item in data[:8]
                    if isinstance(item, dict)
                ]
            }

        if intent == "help":
            return {"tool_names": self._tool_names()}

        return None

    def _build_response(
        self,
        intent: str,
        category: str,
        reply: str,
        next_action: str,
        tool_used: str | None = None,
        tool_result: dict | None = None,
        raw_intent: dict | None = None,
        llm_raw_response: dict | None = None,
        debug: bool = False,
        success: bool = True,
        error_message: str | None = None,
        data: dict | None = None,
        session_id: str | None = None,
    ) -> dict:
        """统一构造聊天响应。"""
        response = {
            "success": success,
            "intent": intent,
            "category": category,
            "reply": reply,
            "tool_used": tool_used,
            "data": data,
            "next_action": next_action,
        }
        if session_id:
            response["session_id"] = session_id
        if debug:
            response["tool_result"] = tool_result
            response["available_tools"] = self.list_tools()
            response["raw_intent"] = raw_intent
            response["llm_raw_response"] = llm_raw_response
            response["debug"] = True
        if error_message:
            response["error_message"] = error_message
        return response

    def run_tool(self, tool_name: str, params: dict | None = None) -> dict:
        """根据工具名执行已注册工具。"""
        tool_spec = get_tool_spec(tool_name)
        if tool_spec is None:
            return {
                "success": False,
                "error_message": f"未注册的工具: {tool_name}",
            }

        handler = tool_spec["handler"]
        try:
            return handler(**(params or {}))
        except Exception as exc:
            logger.exception("Agent 工具执行失败: %s", tool_name)
            return {
                "success": False,
                "error_message": f"工具执行失败: {exc}",
            }

    def _build_help_response(self, message: str, debug: bool = False) -> dict:
        """返回帮助型回复。"""
        return self._build_response(
            intent="help",
            category="help",
            reply=(
                f"我还没有从这句话里拿到足够明确的任务：{message}\n"
                "你可以问我当前模型、模型文件状态、最近实验记录，或者直接上传 CSV 做分析。"
            ),
            next_action="可以试试“当前用的是哪个模型？”、“检查模型文件是否齐全”或“查看最近实验记录”。",
            tool_used=None,
            tool_result=None,
            debug=debug,
            data={"tool_names": self._tool_names()},
        )

    def _build_builtin_response(self, intent: str, debug: bool = False) -> dict:
        """返回内置基础对话。"""
        if intent == "agent_identity":
            return self._build_response(
                intent=intent,
                category="builtin",
                reply="我是 RamanAgent，一个面向拉曼光谱分析和甲醇浓度预测的智能助手。你可以把我当成会聊天、也会调真实工具的实验分析搭子。",
                next_action="如果你想看真实系统状态，可以直接问我当前模型、模型文件，或者上传 CSV 让我分析。",
                debug=debug,
                data=None,
            )
        if intent == "agent_capabilities":
            return self._build_response(
                intent=intent,
                category="builtin",
                reply="我能做三类事：一类是调用真实工具，比如查当前模型、检查模型文件、看历史记录、分析 CSV；一类是解释 Raman 光谱、机器学习和项目开发问题；还有一类是做普通对话和使用引导。",
                next_action="如果你想马上开始，可以先上传一个 CSV，或者先问我“当前用的是哪个模型？”。",
                debug=debug,
                data={"tool_names": self._tool_names()},
            )
        if intent == "user_identity":
            return self._build_response(
                intent=intent,
                category="builtin",
                reply="当前系统没有登录用户体系，所以我没法确认你是谁，也不会假装知道你的身份。",
                next_action="不过我仍然可以继续帮你看模型、查历史记录或者分析样品。",
                debug=debug,
                data=None,
            )
        return self._build_response(
            intent="upload_help",
            category="builtin",
            reply="上传 CSV 最直接的方式是使用前端页面里的“上传分析”区域，或者调用 `/api/agent/analyze-file`。文件格式建议是两列：第一列波数，第二列强度。",
            next_action="准备好 CSV 后就可以开始分析；如果你愿意，我也可以先告诉你页面上每个区域分别做什么。",
            debug=debug,
            data=None,
        )

    def _should_use_llm_intent_fallback(self, intent_info: dict) -> bool:
        """仅在规则结果不明确时启用 LLM 二级分类。"""
        category = intent_info.get("category")
        intent = intent_info.get("intent")
        confidence = float(intent_info.get("confidence", 0.0) or 0.0)
        return category == "general_chat" and intent == "general_chat" and confidence < 0.9

    def _map_llm_intent_to_route(self, message: str, llm_result: dict) -> dict:
        """把 LLM 分类结果映射回现有 Agent 路由。"""
        text = (message or "").strip()
        lowered = text.lower()
        slots = llm_result.get("slots", {}) or {}
        intent = llm_result.get("intent", "unknown")

        if intent == "model_info":
            if any(keyword in text for keyword in ("模型文件", "工件")) or "artifact" in lowered:
                return {"intent": "check_current_model", "category": "tool", "confidence": llm_result.get("confidence", 0.0), "params": {}}
            return {"intent": "get_current_model", "category": "tool", "confidence": llm_result.get("confidence", 0.0), "params": {}}

        if intent == "history_query":
            return {
                "intent": "get_experiment_history",
                "category": "tool",
                "confidence": llm_result.get("confidence", 0.0),
                "params": {"limit": int(slots.get("limit", 10) or 10)},
            }

        if intent == "file_analysis":
            return {"intent": "predict_methanol", "category": "tool", "confidence": llm_result.get("confidence", 0.0), "params": {}}

        if intent == "report_generation":
            return {"intent": "generate_report", "category": "tool", "confidence": llm_result.get("confidence", 0.0), "params": {}}

        if intent == "spectral_quality":
            return {"intent": "analyze_spectrum_quality", "category": "tool", "confidence": llm_result.get("confidence", 0.0), "params": {}}

        if intent == "peak_analysis":
            return {"intent": "detect_peaks", "category": "tool", "confidence": llm_result.get("confidence", 0.0), "params": {}}

        if intent == "compare_history":
            return {
                "intent": "find_similar_history",
                "category": "tool",
                "confidence": llm_result.get("confidence", 0.0),
                "params": {"current_prediction_result": slots.get("current_prediction_result")},
            }

        if intent == "raman_qa":
            return {"intent": "raman_qa", "category": "general_chat", "confidence": llm_result.get("confidence", 0.0), "params": {}}

        if intent == "general_chat":
            return {"intent": "general_chat", "category": "general_chat", "confidence": llm_result.get("confidence", 0.0), "params": {}}

        return {"intent": "general_chat", "category": "general_chat", "confidence": 0.0, "params": {}}

    def _resolve_intent_with_fallback(self, message: str) -> dict:
        """先走规则路由，不明确时再尝试 LLM 分类。"""
        rule_intent = detect_intent(message)
        if not self._should_use_llm_intent_fallback(rule_intent):
            return rule_intent

        try:
            llm_result = self._get_llm_intent_classifier().classify(message)
            mapped = self._map_llm_intent_to_route(message, llm_result)
            mapped["llm_fallback"] = llm_result
            mapped["rule_fallback"] = rule_intent
            return mapped
        except Exception as exc:
            logger.info("LLM 意图分类 fallback 不可用，降级为 general_chat: %s", exc)
            degraded = dict(rule_intent)
            degraded["llm_fallback_error"] = str(exc)
            return degraded

    def _build_general_chat_response(self, message: str, intent_info: dict, debug: bool = False, session_id: str | None = None) -> dict:
        """处理普通对话、寒暄和轻量问答。"""
        system_context = {"current_model_version": self._current_model_version()}
        intent = intent_info.get("intent", "general_chat")
        category = intent_info.get("category", "general_chat")
        local_reply = build_general_chat_local_reply(message, system_context=system_context, intent=intent)

        llm_response = None
        llm_reply = ""
        if intent == "general_chat":
            llm_response = self.general_chat(message, context=system_context)
            llm_reply = (llm_response or {}).get("reply", "") or ""

        reply = llm_reply or local_reply
        next_action = "如果你想继续聊基础问题，也可以直接问我；如果要做 Raman 分析，我也能继续帮你。"
        if intent in {"capability_intro", "smalltalk", "gratitude", "weather", "joke"}:
            next_action = "如果你想继续聊 Raman、光谱、模型或 CSV 分析，我也可以接着帮你。"

        response = self._build_response(
            intent=intent,
            category=category,
            reply=reply,
            next_action=next_action,
            tool_used=None,
            tool_result=None,
            raw_intent=intent_info,
            llm_raw_response=(llm_response or {}).get("raw_response") if llm_response else None,
            debug=debug,
            success=True,
            error_message=None,
            data=None,
            session_id=session_id,
        )
        if llm_response and not llm_response.get("success"):
            response["llm_note"] = llm_response.get("error_message")
        return response

    def general_chat(self, message: str, context: dict | None = None) -> dict:
        """处理普通对话、知识问答和建议类问题。"""
        system_context = {"current_model_version": self._current_model_version()}
        if context:
            system_context.update(context)
        return LLMService().generate_general_reply(message, system_context=system_context)

    def _resolve_history_identifier(self, params: dict) -> tuple[str | None, str | None]:
        """支持显式 history_id 或“第 N 条记录”两种详情定位方式。"""
        history_id = params.get("history_id")
        if history_id:
            return str(history_id), None

        history_index = params.get("history_index")
        if not history_index:
            return None, "未提供 history_id，也没有识别到“第几条记录”。"

        data = list_analysis_history(limit=max(int(history_index), 10), offset=0)
        items = data.get("items", [])
        index = int(history_index) - 1
        if index < 0 or index >= len(items):
            return None, f"当前历史记录不足 {history_index} 条，无法查看详情。"
        return str(items[index]["task_id"]), None

    def chat(
        self,
        message: str,
        extra_params: dict | None = None,
        debug: bool = False,
        session_id: str | None = None,
    ) -> dict:
        """根据用户问题自动识别意图并调用工具。"""
        try:
            contextual_response = self._handle_session_context_request(message, session_id=session_id, debug=debug)
            if contextual_response is not None:
                return contextual_response

            plan = self._planner.plan(message)
            if plan.is_compound:
                return self._execute_agent_plan(
                    plan,
                    message,
                    params=extra_params or {},
                    debug=debug,
                    session_id=session_id,
                )

            intent_info = self._resolve_intent_with_fallback(message)
            intent = intent_info["intent"]
            category = intent_info.get("category", "help")
            params = dict(intent_info.get("params", {}))
            params.update(extra_params or {})

            if category == "help":
                response = self._build_help_response(message, debug=debug)
                if session_id:
                    response["session_id"] = session_id
                return response

            if category == "general_chat":
                return self._build_general_chat_response(message, intent_info, debug=debug, session_id=session_id)

            if category == "builtin":
                response = self._build_builtin_response(intent, debug=debug)
                if session_id:
                    response["session_id"] = session_id
                return response

            if intent == "predict_methanol" and not params.get("file_path"):
                return self._build_response(
                    intent=intent,
                    category="tool",
                    reply="需要上传 CSV 文件，请使用 /api/agent/analyze-file 或前端上传入口。",
                    next_action="准备好 Raman CSV 文件后，再通过上传入口发起分析。",
                    tool_used="predict_methanol",
                    tool_result=None,
                    raw_intent=intent_info,
                    debug=debug,
                    data=None,
                    session_id=session_id,
                )

            if intent == "generate_report" and not params.get("result"):
                return self._build_response(
                    intent=intent,
                    category="tool",
                    reply="要生成报告，通常需要先有一次有效的分析结果。你可以先上传 CSV 做分析，或者提供已有结果上下文。",
                    next_action="如果你现在就想继续，可以先通过 /api/agent/analyze-file 上传 CSV。",
                    tool_used=intent,
                    tool_result=None,
                    raw_intent=intent_info,
                    debug=debug,
                    data=None,
                    session_id=session_id,
                )

            if intent == "find_similar_history" and not params.get("current_prediction_result"):
                return self._build_response(
                    intent=intent,
                    category="tool",
                    reply="如果要和历史样品做相似度对比，通常需要先有当前样品的预测结果或先上传 CSV 文件。",
                    next_action="你可以先上传 CSV 做分析，或者先让我列出最近实验记录。",
                    tool_used=intent,
                    tool_result=None,
                    raw_intent=intent_info,
                    debug=debug,
                    data=None,
                    session_id=session_id,
                )

            spectral_intents = {
                "detect_peaks",
                "analyze_spectrum_quality",
                "analyze_baseline_quality",
                "professional_spectral_analysis",
            }
            detail_intents = {"get_history_detail", "get_experiment_detail"}
            if intent in spectral_intents:
                if params.get("file_path") and not params.get("csv_path"):
                    params["csv_path"] = params.pop("file_path")
                if params.get("prediction_result") and intent == "professional_spectral_analysis" and not params.get("csv_path"):
                    return self._build_response(
                        intent=intent,
                        category="tool",
                        reply="需要先上传 CSV 文件，或指定某条历史记录。",
                        next_action="请通过 /api/agent/analyze-file 上传 CSV，以便同时分析光谱和预测结果。",
                        tool_used=intent,
                        tool_result=None,
                        raw_intent=intent_info,
                        debug=debug,
                        data=None,
                        session_id=session_id,
                    )
                if not params.get("csv_path"):
                    return self._build_response(
                        intent=intent,
                        category="tool",
                        reply="需要先上传 CSV 文件，或指定某条历史记录。",
                        next_action="请通过 /api/agent/analyze-file 上传 CSV 文件后再进行专业光谱分析。",
                        tool_used=intent,
                        tool_result=None,
                        raw_intent=intent_info,
                        debug=debug,
                        data=None,
                        session_id=session_id,
                    )

            if intent in detail_intents:
                history_id, error_message = self._resolve_history_identifier(params)
                if error_message:
                    return self._build_response(
                        intent=intent,
                        category="tool",
                        reply=error_message,
                        next_action="你可以先查看最近实验记录，或者直接提供 task_id。",
                        tool_used=intent,
                        tool_result=None,
                        raw_intent=intent_info,
                        debug=debug,
                        success=False,
                        error_message=error_message,
                        data=None,
                        session_id=session_id,
                    )
                params = {"history_id": history_id}

            tool_result = self.run_tool(intent, params)
            success = bool(tool_result.get("success"))
            compact_data = self._compact_data(intent, tool_result, params)

            if intent == "check_artifacts":
                missing = tool_result.get("missing_files", [])
                reply = "模型文件检查完成，所有核心文件齐全。" if success else f"模型文件检查完成，但存在 {len(missing)} 个缺失文件。"
                next_action = "如果文件齐全，可以继续上传 CSV 文件进行预测。"
            elif intent == "list_history":
                total = tool_result.get("total", 0)
                reply = f"历史记录查询完成，目前共找到 {total} 条记录。"
                next_action = "如果你想查看某条详情，可以继续说“查看第 1 条记录详情”。"
            elif intent in detail_intents:
                reply = "历史记录详情已查询完成。" if success else tool_result.get("error_message", "历史记录查询失败。")
                next_action = "如果需要，可以继续生成报告或对比其他历史记录。"
            elif intent == "get_experiment_history":
                total = tool_result.get("total", 0)
                reply = f"实验记录查询完成，目前共找到 {total} 条记录。"
                next_action = "如果你想看单次详情，可以继续提供 task_id 或说“查看第 1 条记录详情”。"
            elif intent == "get_current_model":
                data = tool_result.get("data", {}) or {}
                reply = f"当前使用的模型版本是 {data.get('model_version', '未知版本')}。"
                next_action = "如果你想确认模型文件是否齐全，可以继续让我检查当前模型。"
            elif intent == "check_current_model":
                data = tool_result.get("data", {}) or {}
                missing = data.get("missing_files", [])
                reply = "当前模型文件检查完成，模型可用。" if success else f"当前模型文件检查完成，但存在 {len(missing)} 个缺失文件。"
                next_action = "模型文件齐全时，可以继续上传 CSV 做分析。"
            elif intent == "list_model_versions":
                data = tool_result.get("data", []) or []
                reply = f"当前已注册 {len(data)} 个模型版本。"
                next_action = "如果你想看当前实际使用的是哪一个模型，可以继续问我当前模型版本。"
            elif intent == "predict_methanol":
                if success:
                    reply = (
                        "样品分析已完成。"
                        f" 当前融合预测值为 {float(tool_result.get('final_prediction', 0.0)):.4f}"
                        f"{(tool_result.get('result') or {}).get('unit', '')}。"
                    )
                    next_action = "如果需要，我可以继续帮你生成报告或补充结果解释。"
                else:
                    reply = tool_result.get("error_message", "样品分析失败。")
                    next_action = "请确认上传的是有效 CSV 文件，或先检查模型文件是否齐全。"
            elif intent == "generate_report":
                reply = "Markdown 报告已生成。" if success else tool_result.get("error_message", "报告生成失败。")
                next_action = "你可以打开报告查看完整内容。"
            elif intent == "explain_result":
                reply = "结果解释已生成。" if success else "大模型解释不可用，已返回降级说明。"
                next_action = "你可以结合图谱和报告继续人工复核。"
            elif intent == "find_similar_history":
                reply = tool_result.get("message", "历史相似样品对比已完成。")
                next_action = "如果你愿意，我也可以继续帮你查看相关历史记录详情。"
            elif intent in spectral_intents:
                reply = "专业光谱分析已完成。" if success else tool_result.get("error_message", "专业光谱分析失败。")
                next_action = "可以结合预测结果、主要峰和质量评估一起判断样品是否需要复测。"
            else:
                reply = "工具调用已完成。"
                next_action = "你可以继续提问或执行下一步分析。"

            if intent == "get_experiment_history":
                compact_data = compact_data or {}
            if intent == "check_current_model":
                compact_data = compact_data or {}

            return self._build_response(
                intent=intent,
                category="tool",
                reply=reply,
                next_action=next_action,
                tool_used=intent,
                tool_result=tool_result,
                raw_intent=intent_info,
                debug=debug,
                success=success,
                error_message=None if success else tool_result.get("error_message", "工具执行失败。"),
                data=compact_data,
                session_id=session_id,
            )
        except Exception as exc:
            logger.exception("Agent chat 执行失败")
            return self._build_response(
                intent="unknown",
                category="help",
                reply=f"Agent 执行失败：{exc}",
                next_action="请稍后重试。",
                tool_used=None,
                tool_result=None,
                raw_intent=None,
                debug=debug,
                success=False,
                error_message=str(exc),
                data=None,
                session_id=session_id,
            )
