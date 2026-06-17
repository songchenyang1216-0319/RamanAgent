"""Catalog of tools that the LLM planner is allowed to reference."""

from __future__ import annotations

from typing import Any

from .tool_schema import ActionSchema, ToolSchema


def _action(
    action_name: str,
    description: str,
    *,
    display_name: str | None = None,
    requires_file: bool = False,
    arg_schema: dict[str, Any] | None = None,
    input_schema: dict[str, Any] | None = None,
    output_schema: dict[str, Any] | None = None,
    required_args: list[str] | None = None,
    default_args: dict[str, Any] | None = None,
    examples: list[dict[str, Any]] | None = None,
    requires_confirmation: bool = False,
    confirmation_message: str = "",
    danger_level: str = "low",
    timeout_seconds: int = 60,
    permissions: list[str] | None = None,
    side_effects: list[str] | None = None,
    visible_to_user: bool = True,
    supports_streaming: bool = False,
    supports_async_task: bool = False,
) -> ActionSchema:
    schema = input_schema or arg_schema or {"type": "object", "properties": {}}
    schema.setdefault("type", "object")
    schema.setdefault("properties", {})
    return ActionSchema(
        action_name=action_name,
        description=description,
        display_name=display_name or action_name,
        requires_file=requires_file,
        input_schema=schema,
        output_schema=output_schema or {"type": "object", "properties": {}},
        required_args=required_args or [],
        default_args=default_args or {},
        examples=examples or [],
        requires_confirmation=requires_confirmation,
        confirmation_message=confirmation_message,
        danger_level=danger_level,
        timeout_seconds=timeout_seconds,
        permissions=permissions or [],
        side_effects=side_effects or ["none"],
        visible_to_user=visible_to_user,
        arg_schema=schema,
        supports_streaming=supports_streaming,
        supports_async_task=supports_async_task,
    )


def _tool(
    tool_name: str,
    display_name: str,
    description: str,
    *,
    category: str,
    actions: dict[str, ActionSchema],
    tags: list[str] | None = None,
    requires_auth: bool = False,
    requires_file: bool = False,
    danger_level: str = "low",
    source: str = "builtin",
    available: bool = True,
    unavailable_reason: str = "",
    permissions: list[str] | None = None,
    examples: list[dict[str, Any]] | None = None,
) -> ToolSchema:
    return ToolSchema(
        tool_name=tool_name,
        display_name=display_name,
        description=description,
        category=category,
        actions=actions,
        tags=tags or [],
        source=source,
        available=available,
        unavailable_reason=unavailable_reason,
        requires_auth=requires_auth,
        requires_file=requires_file,
        permissions=permissions or [],
        danger_level=danger_level,
        input_schema={"type": "object", "properties": {}},
        output_schema={"type": "object", "properties": {}},
        examples=examples or [],
    )


class ToolCatalog:
    def __init__(self) -> None:
        self._tools = self._build_tools()
        self._load_mcp_tools()

    def _build_tools(self) -> dict[str, ToolSchema]:
        return {
            "raman_pipeline": _tool(
                "raman_pipeline",
                "Raman Pipeline",
                "运行 Raman 光谱算法注册表和可组合 Pipeline。",
                category="raman",
                tags=["raman", "pipeline", "spectrum"],
                actions={
                    "list_algorithms": _action("list_algorithms", "列出 Raman Pipeline 算法。"),
                    "list_pipeline_templates": _action("list_pipeline_templates", "列出内置 Pipeline 模板。"),
                    "validate_pipeline": _action("validate_pipeline", "校验 Pipeline 步骤。"),
                    "run_custom_pipeline": _action("run_custom_pipeline", "运行自定义 Raman Pipeline。", requires_file=True, timeout_seconds=180, side_effects=["read_file", "write_file", "long_running"], supports_async_task=True),
                    "run_template_pipeline": _action("run_template_pipeline", "运行内置 Raman Pipeline 模板。", requires_file=True, timeout_seconds=180, side_effects=["read_file", "write_file", "long_running"], supports_async_task=True),
                    "compare_pipelines": _action("compare_pipelines", "比较多个预处理 Pipeline。", requires_file=True, timeout_seconds=240, side_effects=["read_file", "write_file", "long_running"], supports_async_task=True),
                    "get_pipeline_history": _action("get_pipeline_history", "查看 Pipeline 历史。"),
                },
            ),
            "raman_model": _tool(
                "raman_model",
                "Raman 甲醇模型",
                "调用旧甲醇预测模型和模型信息能力。",
                category="raman",
                tags=["raman", "methanol", "model"],
                actions={
                    "predict_methanol_concentration": _action("predict_methanol_concentration", "调用 MethanolPredictor.predict 预测甲醇浓度。", requires_file=True, timeout_seconds=180, side_effects=["read_file", "write_file", "long_running"]),
                    "get_model_info": _action("get_model_info", "查看当前 Raman/甲醇模型信息。"),
                },
            ),
            "rag": _tool(
                "rag",
                "RAG 检索问答",
                "基于会话文件、知识库或混合范围进行检索问答。",
                category="knowledge",
                tags=["rag", "knowledge_base"],
                actions={
                    "answer": _action("answer", "执行 RAG 问答。", timeout_seconds=120, side_effects=["read_file"]),
                    "rebuild_index": _action("rebuild_index", "重建 RAG 索引。", requires_confirmation=True, confirmation_message="重建索引会改写向量索引并可能耗时较久，请确认是否继续。", danger_level="medium", timeout_seconds=300, side_effects=["write_file", "long_running"]),
                },
            ),
            "web_search": _tool(
                "web_search",
                "联网搜索",
                "搜索外部网页并返回带来源的答案。",
                category="knowledge",
                tags=["web", "search"],
                actions={
                    "answer_with_sources": _action("answer_with_sources", "联网搜索并回答。"),
                },
            ),
            "document_tool": _tool(
                "document_tool",
                "文档处理",
                "对上传文档进行摘要、提纲、重点提取和翻译等处理。",
                category="document",
                tags=["document"],
                requires_file=True,
                actions={
                    "summarize": _action("summarize", "总结文档。", requires_file=True),
                    "outline": _action("outline", "提取文档大纲。", requires_file=True),
                    "extract_key_points": _action("extract_key_points", "提取重点。", requires_file=True),
                    "translate": _action("translate", "翻译文档。", requires_file=True),
                    "polish": _action("polish", "润色文档。", requires_file=True),
                    "ocr": _action("ocr", "对图片或扫描 PDF 执行 OCR。", requires_file=True, timeout_seconds=240, side_effects=["read_file", "write_file", "long_running"]),
                },
            ),
            "file_tool": _tool(
                "file_tool",
                "文件工具",
                "读取文件元数据和轻量信息。",
                category="file",
                tags=["file"],
                actions={
                    "file_info": _action("file_info", "查看文件基本信息。", requires_file=True),
                    "download": _action("download", "下载文件。", requires_file=True, requires_confirmation=False, side_effects=["read_file"]),
                    "delete": _action("delete", "删除文件。", requires_file=True, requires_confirmation=True, confirmation_message="删除文件不可恢复，请确认是否继续。", danger_level="high", side_effects=["delete_file"]),
                },
            ),
            "report_tool": _tool(
                "report_tool",
                "报告工具",
                "生成或导出报告。",
                category="report",
                tags=["report"],
                actions={
                    "generate_markdown": _action("generate_markdown", "生成 Markdown 报告。"),
                    "export_report": _action("export_report", "导出报告。", timeout_seconds=180, side_effects=["write_file", "long_running"]),
                },
            ),
            "project_tool": _tool(
                "project_tool",
                "项目工具",
                "创建、查询和维护项目。",
                category="project",
                requires_auth=True,
                tags=["project"],
                actions={
                    "list_projects": _action("list_projects", "列出项目。", permissions=["project:view"]),
                    "create_project": _action("create_project", "创建项目。", permissions=["project:create"], side_effects=["modify_project"]),
                },
            ),
            "task_tool": _tool(
                "task_tool",
                "任务工具",
                "创建、查询、取消长任务。",
                category="task",
                tags=["task"],
                actions={
                    "create_task": _action("create_task", "创建异步任务。", side_effects=["long_running"]),
                    "get_task": _action("get_task", "查看任务详情。"),
                    "cancel_task": _action("cancel_task", "取消任务。", requires_confirmation=True, confirmation_message="取消任务可能中断正在运行的分析，请确认是否继续。", danger_level="medium", side_effects=["long_running"]),
                },
            ),
            "memory_tool": _tool(
                "memory_tool",
                "记忆工具",
                "读取或更新用户记忆。",
                category="memory",
                requires_auth=True,
                tags=["memory"],
                actions={
                    "get_memory": _action("get_memory", "读取用户记忆。", permissions=["memory:view"]),
                    "update_memory": _action("update_memory", "更新用户记忆。", requires_confirmation=True, permissions=["memory:edit"], side_effects=["write_file"]),
                },
            ),
            "model_tool": _tool(
                "model_tool",
                "模型工具",
                "查看和切换大模型。",
                category="model",
                tags=["model"],
                actions={
                    "get_current_model": _action("get_current_model", "查看当前大模型。"),
                    "list_models": _action("list_models", "列出可用模型。"),
                    "select_model": _action("select_model", "切换模型。", requires_confirmation=True, confirmation_message="切换模型会影响后续对话和工具规划，请确认是否继续。", danger_level="medium", side_effects=["modify_model"]),
                },
            ),
            "skill_tool": _tool(
                "skill_tool",
                "Skill 工具",
                "查看、启用、禁用和执行 Skill。",
                category="skill",
                tags=["skill"],
                actions={
                    "list_skills": _action("list_skills", "列出 Skill。"),
                    "execute_skill": _action("execute_skill", "执行 Skill。", requires_confirmation=True, confirmation_message="执行上传的可执行 Skill 存在较高风险，请确认是否继续。", danger_level="high", timeout_seconds=120, side_effects=["execute_code"]),
                    "set_skill_enabled": _action("set_skill_enabled", "启用或禁用 Skill。", requires_confirmation=True, danger_level="medium", side_effects=["write_file"]),
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

    def _load_mcp_tools(self) -> None:
        try:
            from backend.mcp import MCPClient

            client = MCPClient()
            for spec in client.list_tool_specs():
                if spec.tool_name not in self._tools:
                    self._tools[spec.tool_name] = spec
        except Exception:
            return
