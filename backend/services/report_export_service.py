"""报告导出服务。"""

from __future__ import annotations

import json
import zipfile
from xml.sax.saxutils import escape as xml_escape
from pathlib import Path
from typing import Any

from backend.agent.tools.spectral_tools.spectral_summary_tool import analyze_spectrum_professionally
from backend.services.file_service import FileCatalogService
from backend.services.model_registry_service import ModelRegistryService
from backend.services.methanol_service import predict_methanol
from backend.services.project_service import ProjectService
from backend.services.report_registry_service import ReportRegistryService
from backend.services.report_service import RamanReportService
from backend.services.task_trace_manager import TaskTraceManager
from backend.services.user_service import UserService
from raman_core.methanol.config import OUTPUT_DIR, PROJECT_ROOT, REPORT_DIR


class ReportExportService:
    def __init__(
        self,
        *,
        file_catalog: FileCatalogService | None = None,
        task_trace_manager: TaskTraceManager | None = None,
        project_service: ProjectService | None = None,
        report_registry: ReportRegistryService | None = None,
        report_service: RamanReportService | None = None,
        user_service: UserService | None = None,
    ) -> None:
        self.file_catalog = file_catalog or FileCatalogService()
        self.task_trace_manager = task_trace_manager or TaskTraceManager()
        self.report_registry = report_registry or ReportRegistryService(file_catalog=self.file_catalog)
        self.project_service = project_service or ProjectService(file_catalog=self.file_catalog, task_trace_manager=self.task_trace_manager, report_service=self.report_registry)
        self.report_service = report_service or RamanReportService()
        self.user_service = user_service or UserService()

    def export_report(
        self,
        *,
        user_id: str,
        is_admin: bool,
        task_id: str | None = None,
        file_id: str | None = None,
        project_id: str | None = None,
        formats: list[str] | None = None,
        title: str | None = None,
    ) -> dict[str, Any]:
        requested_formats = [str(item).strip().lower() for item in (formats or ["markdown"]) if str(item).strip()]
        if "markdown" not in requested_formats:
            requested_formats.insert(0, "markdown")
        file_item = self._resolve_source_file(task_id=task_id, file_id=file_id, user_id=user_id, is_admin=is_admin)
        if file_item is None:
            raise KeyError("未找到可导出的源文件。")
        if project_id:
            project = self.project_service.get_project(project_id, user_id=user_id, is_admin=is_admin)
            if project is None:
                raise KeyError("项目不存在。")
        else:
            project_id = file_item.get("project_id")
            project = self.project_service.get_project(project_id, user_id=user_id, is_admin=is_admin) if project_id else None
        source_path = (PROJECT_ROOT / str(file_item.get("path") or "")).resolve()
        model_info = {}
        current_model_response = ModelRegistryService().get_current_model()
        if current_model_response.get("success"):
            model_info = dict(current_model_response.get("data") or {})
        result = predict_methanol(source_path)
        professional_analysis = analyze_spectrum_professionally(source_path, result)
        context = {
            "project_name": project.get("name") if project else "未绑定项目",
            "username": (self.user_service.get_user_by_id(user_id) or {}).get("username") or user_id,
            "title": title or f"{file_item.get('original_filename') or file_item.get('filename')} Raman 分析报告",
        }
        report_payload = self.report_service.generate(
            result=result,
            llm_explanation="当前导出流程未额外调用大模型解释。",
            professional_analysis=professional_analysis if professional_analysis.get("success") else {},
            model_info=model_info,
            experiment_metadata={},
            context=context,
        )
        generated = {
            "markdown": report_payload.get("report_markdown_path"),
            "json": self._write_json_export(report_payload, result, professional_analysis, context),
            "pdf": None,
            "docx": None,
        }
        errors: list[str] = []
        if "docx" in requested_formats:
            try:
                generated["docx"] = self._write_docx_export(report_payload, context)
            except Exception as exc:
                errors.append(f"DOCX 导出失败：{exc}")
        if "pdf" in requested_formats:
            errors.append("PDF 导出当前为可选能力，当前环境未安装中文 PDF 依赖，已跳过。")
        status = "success" if not errors else "success_with_warnings"
        record = self.report_registry.create_report_record(
            user_id=user_id,
            project_id=project_id,
            task_id=task_id,
            file_id=str(file_item.get("file_id") or ""),
            title=context["title"],
            report_type="raman_analysis",
            markdown_path=report_payload.get("report_markdown_path"),
            html_path=report_payload.get("report_html_path"),
            pdf_path=generated.get("pdf"),
            docx_path=generated.get("docx"),
            json_path=generated.get("json"),
            status=status,
            error_message="；".join(errors) if errors else None,
        )
        return {
            "success": True,
            "report": record,
            "generated_files": generated,
            "warnings": errors,
        }

    def _resolve_source_file(self, *, task_id: str | None, file_id: str | None, user_id: str, is_admin: bool) -> dict[str, Any] | None:
        if file_id:
            return self.file_catalog.get_file_for_user(file_id, user_id=user_id, is_admin=is_admin)
        if task_id:
            trace = self.task_trace_manager.get_task_trace(task_id, user_id=user_id, is_admin=is_admin)
            task = trace.get("task") or {}
            task_file_id = str(task.get("file_id") or "").strip()
            if task_file_id:
                return self.file_catalog.get_file_for_user(task_file_id, user_id=user_id, is_admin=is_admin)
        return None

    def _write_json_export(self, report_payload: dict[str, Any], result: dict[str, Any], professional_analysis: dict[str, Any], context: dict[str, Any]) -> str:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        json_name = f"{report_payload['report_id']}.json"
        json_path = REPORT_DIR / json_name
        json_path.write_text(
            json.dumps(
                {
                    "context": context,
                    "report": report_payload,
                    "result": result,
                    "professional_analysis": professional_analysis,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return str(json_path.relative_to(PROJECT_ROOT)).replace("\\", "/")

    def _write_docx_export(self, report_payload: dict[str, Any], context: dict[str, Any]) -> str:
        markdown_path = (PROJECT_ROOT / str(report_payload.get("report_markdown_path") or "")).resolve()
        if not markdown_path.exists():
            markdown_name = str(report_payload.get("report_markdown_file") or Path(str(report_payload.get("report_markdown_path") or "")).name)
            markdown_path = (REPORT_DIR / markdown_name).resolve()
        docx_name = f"{report_payload['report_id']}.docx"
        docx_path = REPORT_DIR / docx_name
        docx_path.parent.mkdir(parents=True, exist_ok=True)
        safe_title = xml_escape(str(context["title"] or "Raman 分析报告"))
        document_xml = self._build_docx_document_xml(context["title"], markdown_path.read_text(encoding="utf-8"))
        content_types_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>"""
        rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>"""
        word_rels_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>"""
        core_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>{safe_title}</dc:title>
  <dc:creator>RamanAgent</dc:creator>
</cp:coreProperties>"""
        app_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>RamanAgent</Application>
</Properties>"""
        with zipfile.ZipFile(docx_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", content_types_xml)
            archive.writestr("_rels/.rels", rels_xml)
            archive.writestr("word/document.xml", document_xml)
            archive.writestr("word/_rels/document.xml.rels", word_rels_xml)
            archive.writestr("docProps/core.xml", core_xml)
            archive.writestr("docProps/app.xml", app_xml)
        return str(docx_path.relative_to(PROJECT_ROOT)).replace("\\", "/")

    def _build_docx_document_xml(self, title: str, markdown_text: str) -> str:
        def _paragraph(text: str) -> str:
            escaped = (
                str(text or "")
                .replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )
            return f"<w:p><w:r><w:t xml:space=\"preserve\">{escaped}</w:t></w:r></w:p>"

        lines = [title, "", *markdown_text.splitlines()]
        body = "".join(_paragraph(line) for line in lines)
        return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:wpc="http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas" xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:wp14="http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" xmlns:w10="urn:schemas-microsoft-com:office:word" xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>{body}<w:sectPr/></w:body>
</w:document>"""
