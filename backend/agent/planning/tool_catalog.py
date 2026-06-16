"""Catalog of tools that the LLM planner is allowed to reference."""

from __future__ import annotations

from typing import Any

from .tool_schema import ActionSchema, ToolSchema


def _action(action_name: str, description: str, *, requires_file: bool = False, arg_schema: dict[str, Any] | None = None) -> ActionSchema:
    return ActionSchema(
        action_name=action_name,
        description=description,
        requires_file=requires_file,
        arg_schema=arg_schema or {},
    )


class ToolCatalog:
    def __init__(self) -> None:
        self._tools = self._build_tools()

    def _build_tools(self) -> dict[str, ToolSchema]:
        return {
            "raman_pipeline": ToolSchema(
                tool_name="raman_pipeline",
                display_name="Raman Pipeline",
                description="运行 Raman 光谱算法注册表和可组合 Pipeline。",
                tags=["raman", "pipeline", "spectrum"],
                actions={
                    "list_algorithms": _action("list_algorithms", "列出 Raman Pipeline 算法。"),
                    "list_pipeline_templates": _action("list_pipeline_templates", "列出内置 Pipeline 模板。"),
                    "validate_pipeline": _action("validate_pipeline", "校验 Pipeline 步骤。"),
                    "run_custom_pipeline": _action("run_custom_pipeline", "运行自定义 Raman Pipeline。", requires_file=True),
                    "run_template_pipeline": _action("run_template_pipeline", "运行内置 Raman Pipeline 模板。", requires_file=True),
                    "compare_pipelines": _action("compare_pipelines", "比较多个预处理 Pipeline。", requires_file=True),
                    "get_pipeline_history": _action("get_pipeline_history", "查看 Pipeline 历史。"),
                },
            ),
            "raman_model": ToolSchema(
                tool_name="raman_model",
                display_name="Raman 甲醇模型",
                description="调用旧甲醇预测模型和模型信息能力。",
                tags=["raman", "methanol", "model"],
                actions={
                    "predict_methanol_concentration": _action("predict_methanol_concentration", "调用 MethanolPredictor.predict 预测甲醇浓度。", requires_file=True),
                    "get_model_info": _action("get_model_info", "查看当前 Raman/甲醇模型信息。"),
                },
            ),
            "rag": ToolSchema(
                tool_name="rag",
                display_name="RAG 检索问答",
                description="基于会话文件、知识库或混合范围进行检索问答。",
                tags=["rag", "knowledge_base"],
                actions={
                    "answer": _action("answer", "执行 RAG 问答。"),
                },
            ),
            "web_search": ToolSchema(
                tool_name="web_search",
                display_name="联网搜索",
                description="搜索外部网页并返回带来源的答案。",
                tags=["web", "search"],
                actions={
                    "answer_with_sources": _action("answer_with_sources", "联网搜索并回答。"),
                },
            ),
            "document_tool": ToolSchema(
                tool_name="document_tool",
                display_name="文档处理",
                description="对上传文档进行摘要、提纲、重点提取和翻译等处理。",
                tags=["document"],
                actions={
                    "summarize": _action("summarize", "总结文档。", requires_file=True),
                    "outline": _action("outline", "提取文档大纲。", requires_file=True),
                    "extract_key_points": _action("extract_key_points", "提取重点。", requires_file=True),
                    "translate": _action("translate", "翻译文档。", requires_file=True),
                    "polish": _action("polish", "润色文档。", requires_file=True),
                },
            ),
            "file_tool": ToolSchema(
                tool_name="file_tool",
                display_name="文件工具",
                description="读取文件元数据和轻量信息。",
                tags=["file"],
                actions={
                    "file_info": _action("file_info", "查看文件基本信息。", requires_file=True),
                },
            ),
            "report_tool": ToolSchema(
                tool_name="report_tool",
                display_name="报告工具",
                description="生成或导出报告。",
                tags=["report"],
                actions={
                    "generate_markdown": _action("generate_markdown", "生成 Markdown 报告。"),
                    "export_report": _action("export_report", "导出报告。"),
                },
            ),
        }

    def get(self, tool_name: str) -> ToolSchema | None:
        return self._tools.get(str(tool_name))

    def has_tool(self, tool_name: str) -> bool:
        return str(tool_name) in self._tools

    def to_prompt_payload(self) -> list[dict[str, Any]]:
        return [tool.to_dict() for tool in self._tools.values()]

    def to_dict(self) -> dict[str, Any]:
        return {"tools": {name: tool.to_dict() for name, tool in self._tools.items()}}

