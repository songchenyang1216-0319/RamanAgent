from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import BaseSkill, SkillResult
from .data_analysis_skill import DataAnalysisSkill
from raman_core.methanol.config import PROJECT_ROOT


class MetadataOnlySkill(BaseSkill):
    name = "metadata-only"
    display_name = "Metadata Skill"
    description = "展示型 Skill。"
    category = "通用"
    usage = ""

    def __init__(self) -> None:
        self.actions = [
            {
                "name": "default",
                "display_name": "默认动作",
                "description": self.description,
                "enabled": True,
                "available": True,
                "status": "ready",
                "unavailable_reason": "",
            }
        ]

    def run(self, **kwargs: Any) -> SkillResult:
        return SkillResult(
            success=True,
            skill_name=self.name,
            action_name=str(kwargs.get("action_name") or "default"),
            summary=self.usage or self.description,
            data={"reply_text": self.usage or self.description, "skill_mode": "executable"},
            errors=[],
        )


class GeneralChatSkill(MetadataOnlySkill):
    name = "general-chat"
    display_name = "普通聊天"
    description = "普通对话、知识解释、规划建议，不主动处理文件。"
    requires_file = False
    usage = "普通聊天默认由模型路由处理；该 Skill 用于能力清单展示与禁用边界说明。"


class DocumentReaderSkill(BaseSkill):
    name = "document-reader"
    display_name = "文档阅读"
    description = "读取 txt/md/pdf/doc/docx/pptx 等文档，提取摘要、重点和正文片段。"
    category = "文档"
    requires_file = True
    supported_file_types = [".txt", ".md", ".markdown", ".pdf", ".doc", ".docx", ".pptx"]
    usage = "上传文档后可以说“总结这个文件”“提取重点”“生成读书笔记”。"

    def __init__(self) -> None:
        self.processor_registry = None
        self.actions = [
            self._action("summarize", "总结文档"),
            self._action("outline", "提取大纲"),
            self._action("extract_key_points", "提取重点"),
            self._action("translate", "翻译"),
            self._action("polish", "润色"),
        ]

    def _action(self, name: str, description: str) -> dict[str, Any]:
        return {"name": name, "display_name": name, "description": description, "enabled": True, "available": True, "status": "ready", "unavailable_reason": ""}

    def _llm_reply_or_empty(self, llm_result: dict[str, Any]) -> str:
        if not llm_result.get("success"):
            return ""
        return str(llm_result.get("reply") or "").strip()

    def _local_document_reply(self, *, action_name: str, filename: str, summary: str, excerpt: str, chunks: list[dict[str, Any]]) -> str:
        clean_excerpt = str(excerpt or "").strip()
        preview_lines = [line.strip() for line in clean_excerpt.splitlines() if line.strip()]
        preview = "\n".join(preview_lines[:12])
        chunk_count = len(chunks or [])
        heading = {
            "summarize": "文档摘要",
            "outline": "文档大纲",
            "extract_key_points": "重点信息",
            "translate": "可翻译内容预览",
            "polish": "可润色内容预览",
        }.get(action_name, "文档处理结果")
        if action_name == "outline":
            body = "\n".join(f"{index + 1}. {line[:120]}" for index, line in enumerate(preview_lines[:10]))
        elif action_name == "extract_key_points":
            body = "\n".join(f"- {line[:140]}" for line in preview_lines[:8])
        else:
            body = preview
        if not body:
            body = "当前文档已解析，但没有提取到可展示的正文预览。"
        return "\n\n".join(
            [
                f"## {heading}",
                f"文件：{filename}",
                summary or f"已读取文档，共提取 {chunk_count} 个正文片段。",
                "当前大模型服务不可用，下面是基于本地解析结果生成的简要内容。",
                body,
            ]
        )

    def run(self, **kwargs: Any) -> SkillResult:
        if self.processor_registry is None:
            from backend.services.file_processor import FileProcessorRegistry

            self.processor_registry = FileProcessorRegistry()
        file_paths = [str(item or "").strip() for item in (kwargs.get("file_paths") or []) if str(item or "").strip()]
        if len(file_paths) > 1:
            action_name = str(kwargs.get("action_name") or "summarize")
            items = []
            excerpts = []
            errors = []
            for raw_path in file_paths:
                path = Path(raw_path)
                if not path.is_absolute():
                    path = PROJECT_ROOT / path
                processed = self.processor_registry.process(
                    path,
                    file_id=kwargs.get("file_id"),
                    user_id=str(kwargs.get("user_id") or "default_user"),
                    conversation_id=str(kwargs.get("conversation_id") or kwargs.get("session_id") or ""),
                )
                item = processed.to_dict()
                item["path"] = str(path)
                item["filename"] = processed.filename or path.name
                items.append(item)
                if processed.success:
                    excerpts.append(f"## {processed.filename or path.name}\n{processed.summary}\n\n{processed.preview[:1200]}")
                else:
                    errors.append(processed.error_message or f"{path.name} 读取失败")
            reply = ""
            if excerpts:
                try:
                    from backend.services.llm_service import LLMService

                    llm_result = LLMService(
                        provider_id=kwargs.get("provider_id"),
                        model_id=kwargs.get("model_id"),
                        user_id=str(kwargs.get("user_id") or "default_user"),
                        conversation_id=str(kwargs.get("conversation_id") or kwargs.get("session_id") or ""),
                    ).generate_general_reply(
                        str(kwargs.get("message") or "请总结这些文件"),
                        system_context={
                            "document_reader_task": "multi_file_summary",
                            "document_excerpt": "\n\n".join(excerpts)[:9000],
                            "source_files": [item.get("filename") for item in items],
                        },
                    )
                    reply = self._llm_reply_or_empty(llm_result)
                except Exception:
                    reply = ""
            if not reply:
                reply = "已读取这些文件：\n" + "\n".join(
                    f"- {item.get('filename')}: {item.get('summary') or item.get('error_message') or '暂无摘要'}"
                    for item in items
                )
            return SkillResult(
                success=not errors or bool(excerpts),
                skill_name=self.name,
                action_name=action_name,
                summary=reply,
                data={"reply_text": reply, "multi_file": True, "file_count": len(file_paths), "files": items, "skill_mode": "executable"},
                errors=errors,
            )
        path = Path(str(kwargs.get("file_path") or "")).expanduser()
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        action_name = str(kwargs.get("action_name") or "summarize")
        user_id = str(kwargs.get("user_id") or "default_user")
        conversation_id = str(kwargs.get("conversation_id") or kwargs.get("session_id") or "")
        processed = self.processor_registry.process(path, file_id=kwargs.get("file_id"), user_id=str(kwargs.get("user_id") or "default_user"), conversation_id=str(kwargs.get("conversation_id") or kwargs.get("session_id") or ""))
        if not processed.success:
            return SkillResult(False, self.name, processed.error_message or "文档读取失败。", action_name=action_name, data=processed.to_dict(), errors=[processed.error_message or "document_read_failed"])
        chunks = [
            {
                "filename": processed.filename,
                "page": chunk.page,
                "section": chunk.section,
                "text": chunk.text,
                "token_estimate": chunk.token_estimate,
            }
            for chunk in processed.chunks[:6]
        ]
        excerpt = "\n\n".join(str(chunk.get("text") or "") for chunk in chunks).strip() or processed.preview[:3000]
        prompt_by_action = {
            "summarize": "请总结这个文档，给出主题、关键结论和可行动要点。",
            "outline": "请提取这个文档的大纲结构。",
            "extract_key_points": "请提取这个文档的重点信息。",
            "translate": "请把相关内容翻译成中文，保留关键术语。",
            "polish": "请对相关内容进行中文润色，保留原意。",
        }
        reply = ""
        try:
            from backend.services.llm_service import LLMService

            llm_result = LLMService(
                provider_id=kwargs.get("provider_id"),
                model_id=kwargs.get("model_id"),
                user_id=user_id,
                conversation_id=conversation_id,
            ).generate_general_reply(
                str(kwargs.get("message") or prompt_by_action.get(action_name) or "请总结这个文件"),
                system_context={
                    "document_reader_task": prompt_by_action.get(action_name) or action_name,
                    "document_excerpt": excerpt,
                    "relevant_chunks": chunks,
                    "source_file": processed.filename,
                },
            )
            reply = self._llm_reply_or_empty(llm_result)
        except Exception:
            reply = ""
        if not reply:
            reply = self._local_document_reply(
                action_name=action_name,
                filename=processed.filename or path.name,
                summary=processed.summary,
                excerpt=excerpt,
                chunks=chunks,
            )
        return SkillResult(
            True,
            self.name,
            processed.summary,
            action_name=action_name,
            data={**processed.to_dict(), "reply_text": reply, "relevant_chunks": chunks, "skill_mode": "executable"},
            errors=[],
        )


class ReportGeneratorSkill(BaseSkill):
    name = "report-generator"
    display_name = "报告生成"
    description = "根据聊天、文件或分析结果生成 Markdown 报告。"
    category = "报告"
    requires_file = False
    supported_file_types = [".txt", ".md", ".csv", ".xlsx", ".pdf", ".docx"]
    usage = "可以根据当前会话和文件处理结果生成 Markdown 报告。"

    def __init__(self) -> None:
        self.workspace_manager = None
        self.actions = [
            {"name": "generate_markdown", "display_name": "生成 Markdown", "description": "生成可下载 Markdown 报告", "enabled": True, "available": True, "status": "ready", "unavailable_reason": ""}
        ]

    def run(self, **kwargs: Any) -> SkillResult:
        if self.workspace_manager is None:
            from backend.services.workspace_manager import WorkspaceManager

            self.workspace_manager = WorkspaceManager()
        user_id = str(kwargs.get("user_id") or "default_user")
        conversation_id = str(kwargs.get("conversation_id") or kwargs.get("session_id") or "")
        message = str(kwargs.get("message") or "报告").strip()
        context = self.workspace_manager.read_workspace_context(user_id, conversation_id)
        markdown = "\n\n".join(
            [
                f"# {message[:60] or '会话报告'}",
                "## 会话摘要",
                str(context.get("context_summary") or "暂无摘要。"),
                "## 当前文件",
                "\n".join(f"- {item.get('original_filename') or item.get('filename')}" for item in context.get("active_files") or []) or "暂无文件。",
            ]
        )
        output = self.workspace_manager.save_output_file(user_id, conversation_id, "agent_report.md", markdown)
        artifact = {"artifact_id": output.get("file_id"), "type": "markdown", "title": "Markdown 报告", "filename": output.get("filename"), "mime_type": output.get("mime_type"), "download_url": output.get("download_url"), "preview_url": output.get("preview_url"), "created_at": output.get("updated_at")}
        return SkillResult(True, self.name, "报告已生成。", action_name="generate_markdown", data={"reply_text": "报告已生成，可在下方下载。", "artifacts": [artifact], "skill_mode": "executable"}, errors=[])


class FileConverterSkill(BaseSkill):
    name = "file-converter"
    display_name = "文件转换"
    description = "在已支持的文本、Markdown、HTML、DOC/DOCX、PDF、CSV、XLSX 之间进行安全转换。"
    category = "文件"
    requires_file = True
    supported_file_types = [".txt", ".md", ".html", ".csv", ".xlsx", ".doc", ".docx", ".pdf"]
    usage = "部分格式转换尚未实现；无法转换时会明确提示，不会假装成功。"
    skill_mode = "executable"

    def __init__(self) -> None:
        self.actions = [
            {"name": "convert_file", "display_name": "转换文件", "description": "把当前文件转换为指定格式。", "enabled": True, "available": True, "status": "ready", "unavailable_reason": ""}
        ]

    def run(self, **kwargs: Any) -> SkillResult:
        message = str(kwargs.get("message") or "")
        target_format = self._extract_target_format(message)
        if not target_format:
            return SkillResult(False, self.name, "请说明要转换成哪种格式，例如 Markdown、HTML、DOCX、CSV 或 XLSX。", action_name="convert_file", errors=["缺少目标格式。"])
        file_id = ""
        for item in kwargs.get("files") or []:
            if isinstance(item, dict) and item.get("file_id"):
                file_id = str(item.get("file_id"))
                break
        if not file_id:
            for item in kwargs.get("file_ids") or []:
                if item:
                    file_id = str(item)
                    break
        if not file_id:
            return SkillResult(False, self.name, "没有找到可转换的当前文件。请先上传文件，或在文件中心选择当前文件。", action_name="convert_file", errors=["缺少 file_id。"])
        try:
            from backend.services.file_converter import FileConverterService

            result = FileConverterService().convert_file(
                file_id=file_id,
                target_format=target_format,
                user_id=str(kwargs.get("user_id") or "default_user"),
                conversation_id=str(kwargs.get("conversation_id") or kwargs.get("session_id") or ""),
            )
        except Exception as exc:
            return SkillResult(False, self.name, str(exc), action_name="convert_file", errors=[str(exc)])
        return SkillResult(
            True,
            self.name,
            result.get("message") or "文件转换完成。",
            action_name="convert_file",
            data={
                "reply_text": result.get("message") or f"文件已转换为 {result.get('actual_format') or target_format}，可以在下方下载。",
                "artifact": result.get("artifact"),
                "artifacts": [result.get("artifact")] if result.get("artifact") else [],
                "output_file": result.get("output_file"),
                "requested_format": result.get("requested_format") or target_format,
                "target_format": result.get("target_format") or target_format,
                "actual_format": result.get("actual_format") or target_format,
                "pdf_export_available": result.get("pdf_export_available"),
                "warnings": result.get("warnings") or [],
                "skill_mode": "executable",
            },
            errors=[],
        )

    def _extract_target_format(self, message: str) -> str:
        lowered = str(message or "").lower()
        aliases = {
            "markdown": "md",
            "md": "md",
            "html": "html",
            "网页": "html",
            "txt": "txt",
            "文本": "txt",
            "docx": "docx",
            "word": "docx",
            "xlsx": "xlsx",
            "excel": "xlsx",
            "csv": "csv",
            "pdf": "pdf",
        }
        for key, value in aliases.items():
            if key in lowered:
                return value
        return ""


class CodeAssistantSkill(MetadataOnlySkill):
    name = "code-assistant"
    display_name = "代码助手"
    description = "解释代码、检查问题、给出修改建议；不会自动执行上传代码。"
    requires_file = True
    supported_file_types = [".py", ".js", ".ts", ".java", ".go", ".html", ".css", ".sql", ".sh"]
    usage = "可以分析代码文本并给出建议，系统不会执行未知代码。"

    def __init__(self) -> None:
        self.processor_registry = None
        self.actions = [
            {
                "name": "explain_code",
                "display_name": "explain_code",
                "description": "解释当前代码文件。",
                "enabled": True,
                "available": True,
                "status": "ready",
                "unavailable_reason": "",
            }
        ]

    def run(self, **kwargs: Any) -> SkillResult:
        if self.processor_registry is None:
            from backend.services.file_processor import FileProcessorRegistry

            self.processor_registry = FileProcessorRegistry()

        path = Path(str(kwargs.get("file_path") or "")).expanduser()
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if not path.exists() or not path.is_file():
            return SkillResult(
                success=False,
                skill_name=self.name,
                action_name=str(kwargs.get("action_name") or "explain_code"),
                summary="没有找到需要解释的代码文件。",
                errors=["代码文件不存在。"],
            )

        processed = self.processor_registry.process(
            path,
            file_id=kwargs.get("file_id"),
            user_id=str(kwargs.get("user_id") or "default_user"),
            conversation_id=str(kwargs.get("conversation_id") or kwargs.get("session_id") or ""),
        )
        if not processed.success:
            return SkillResult(
                success=False,
                skill_name=self.name,
                action_name=str(kwargs.get("action_name") or "explain_code"),
                summary=processed.error_message or "代码读取失败。",
                data=processed.to_dict(),
                errors=[processed.error_message or "code_read_failed"],
            )

        excerpt = "\n\n".join(str(chunk.text or "") for chunk in processed.chunks[:4]).strip() or processed.preview[:4000]
        reply = ""
        try:
            from backend.services.llm_service import LLMService

            llm_result = LLMService(
                provider_id=kwargs.get("provider_id"),
                model_id=kwargs.get("model_id"),
                user_id=str(kwargs.get("user_id") or "default_user"),
                conversation_id=str(kwargs.get("conversation_id") or kwargs.get("session_id") or ""),
            ).generate_general_reply(
                str(kwargs.get("message") or "请详细解释这个代码文件"),
                system_context={
                    "code_task": "explain_code",
                    "code_excerpt": excerpt,
                    "source_file": processed.filename or path.name,
                    "code_language": path.suffix.lower().lstrip("."),
                },
            )
            if llm_result.get("success"):
                reply = str(llm_result.get("reply") or "").strip()
        except Exception:
            reply = ""

        if not reply:
            preview_lines = [line.rstrip() for line in excerpt.splitlines()[:40]]
            preview = "\n".join(preview_lines).strip() or "当前代码文件已读取，但没有提取到可展示内容。"
            reply = "\n\n".join(
                [
                    "## 代码文件已读取",
                    f"文件：{processed.filename or path.name}",
                    processed.summary or f"已读取代码文件，共 {len(preview_lines)} 行预览。",
                    "当前大模型服务不可用，下面先给你代码预览；恢复模型后可继续做逐段讲解、逻辑梳理和问题排查。",
                    preview,
                ]
            )

        return SkillResult(
            success=True,
            skill_name=self.name,
            action_name=str(kwargs.get("action_name") or "explain_code"),
            summary=processed.summary,
            data={
                **processed.to_dict(),
                "reply_text": reply,
                "code_excerpt": excerpt,
                "skill_mode": "executable",
            },
            errors=[],
        )


class WorkspaceManagerSkill(MetadataOnlySkill):
    name = "workspace-manager"
    display_name = "工作区管理"
    description = "管理当前文件、最近文件、任务状态、运行产物和历史记录。"
    requires_file = False
    usage = "工作区管理主要通过右侧抽屉和文件中心 API 提供。"


class ImageUnderstandingSkill(BaseSkill):
    name = "image-understanding"
    display_name = "图片理解"
    description = "图片描述和 OCR 预留；视觉模型不可用时会明确提示。"
    category = "视觉技能"
    requires_file = True
    supported_file_types = [".png", ".jpg", ".jpeg", ".webp", ".bmp"]
    usage = "图片理解需要支持视觉的模型；否则只返回文件元数据和清楚提示。"
    skill_mode = "executable"

    def __init__(self) -> None:
        self.delegate = None
        self.actions = [
            {"name": "classify_image_type", "display_name": "classify_image_type", "description": "判断图片类型。", "enabled": True, "available": True, "status": "ready", "unavailable_reason": ""},
            {"name": "analyze_general_image", "display_name": "analyze_general_image", "description": "普通图片内容分析。", "enabled": True, "available": True, "status": "ready", "unavailable_reason": ""},
            {"name": "ocr_extract_text", "display_name": "ocr_extract_text", "description": "图片文字提取。", "enabled": True, "available": True, "status": "ready", "unavailable_reason": ""},
            {"name": "image_quality_check", "display_name": "image_quality_check", "description": "图片基础质量检测。", "enabled": True, "available": True, "status": "ready", "unavailable_reason": ""},
        ]

    def run(self, **kwargs: Any) -> SkillResult:
        if self.delegate is None:
            from .image_router_skill import ImageRouterSkill

            self.delegate = ImageRouterSkill()
        action_name = str(kwargs.get("action_name") or "classify_image_type")
        result = self.delegate.run(**kwargs)
        payload = dict(result.data or {})
        payload["skill_mode"] = "executable"
        payload["delegate_skill_name"] = self.delegate.name
        return SkillResult(
            success=result.success,
            skill_name=self.name,
            action_name=action_name,
            summary=result.summary,
            data=payload,
            plots=list(result.plots or []),
            errors=list(result.errors or []),
        )


class TableAnalysisAliasSkill(BaseSkill):
    name = "table-analysis"
    display_name = "表格分析"
    description = "CSV/Excel 分析，支持缺失值、统计、分组、查询、排序和清洗建议。"
    category = "数据技能"
    requires_file = True
    supported_file_types = [".csv", ".xlsx", ".xls"]
    usage = "上传普通 CSV/Excel 后可做缺失值、统计、分组和查询。"
    skill_mode = "executable"

    def __init__(self) -> None:
        self.delegate = DataAnalysisSkill()
        self.actions = self.delegate.get_actions()

    def run(self, **kwargs: Any) -> SkillResult:
        action_name = str(kwargs.get("action_name") or "summarize_table")
        file_paths = [str(item or "").strip() for item in (kwargs.get("file_paths") or []) if str(item or "").strip()]
        if len(file_paths) > 1:
            summaries = []
            items = []
            errors = []
            for raw_path in file_paths:
                path = Path(raw_path)
                if not path.is_absolute():
                    path = PROJECT_ROOT / path
                result = self.delegate.run(**{**kwargs, "file_path": str(path), "file_paths": []})
                payload = dict(result.data or {})
                item = {
                    "file_path": str(path),
                    "filename": path.name,
                    "success": bool(result.success),
                    "summary": result.summary,
                    "action_name": result.action_name or action_name,
                    "data": payload,
                    "errors": list(result.errors or []),
                }
                items.append(item)
                if result.success:
                    summaries.append(f"- {path.name}: {result.summary}")
                else:
                    errors.extend(result.errors or [f"{path.name} 分析失败"])
                    summaries.append(f"- {path.name}: 分析失败")
            reply = "已按文件分别完成表格分析：\n" + "\n".join(summaries)
            return SkillResult(
                success=not errors,
                skill_name=self.name,
                action_name=action_name,
                summary=reply,
                data={
                    "reply_text": reply,
                    "multi_file": True,
                    "file_count": len(file_paths),
                    "results": items,
                    "skill_mode": "executable",
                    "delegate_skill_name": self.delegate.name,
                },
                errors=errors,
            )
        result = self.delegate.run(**kwargs)
        payload = dict(result.data or {})
        payload["skill_mode"] = "executable"
        payload["delegate_skill_name"] = self.delegate.name
        return SkillResult(
            success=result.success,
            skill_name=self.name,
            action_name=action_name,
            summary=result.summary,
            data=payload,
            plots=list(result.plots or []),
            errors=list(result.errors or []),
        )
