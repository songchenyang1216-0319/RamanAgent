"""批量 Raman CSV 分析服务。"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from backend.agent.tools.spectral_tools.spectral_summary_tool import analyze_spectrum_professionally
from backend.services.file_service import FileCatalogService
from backend.services.project_service import ProjectService
from backend.services.report_export_service import ReportExportService
from backend.services.task_trace_manager import TaskTraceManager
from backend.services.workspace_manager import WorkspaceManager
from backend.services.methanol_service import predict_methanol
from raman_core.methanol.config import PROJECT_ROOT


class BatchAnalysisService:
    def __init__(
        self,
        *,
        file_catalog: FileCatalogService | None = None,
        task_trace_manager: TaskTraceManager | None = None,
        workspace_manager: WorkspaceManager | None = None,
        project_service: ProjectService | None = None,
        report_export_service: ReportExportService | None = None,
    ) -> None:
        self.file_catalog = file_catalog or FileCatalogService()
        self.workspace_manager = workspace_manager or WorkspaceManager()
        self.task_trace_manager = task_trace_manager or TaskTraceManager(workspace_manager=self.workspace_manager)
        self.project_service = project_service or ProjectService(file_catalog=self.file_catalog, task_trace_manager=self.task_trace_manager)
        self.report_export_service = report_export_service or ReportExportService(file_catalog=self.file_catalog, task_trace_manager=self.task_trace_manager, project_service=self.project_service)

    def batch_analyze(
        self,
        *,
        user_id: str,
        conversation_id: str | None,
        file_ids: list[str],
        project_id: str | None,
        options: dict[str, Any] | None,
        is_admin: bool = False,
    ) -> dict[str, Any]:
        if not file_ids:
            raise ValueError("file_ids 不能为空。")
        files = self.file_catalog.get_files_by_ids(file_ids, user_id=user_id, is_admin=is_admin)
        if not files:
            raise KeyError("没有找到可分析的文件。")
        if len(files) != len(file_ids):
            missing = [item for item in file_ids if item not in {value.get("file_id") for value in files}]
            raise PermissionError(f"以下文件不存在或无权限访问：{', '.join(missing)}")
        if project_id:
            project = self.project_service.get_project(project_id, user_id=user_id, is_admin=is_admin)
            if project is None:
                raise KeyError("项目不存在。")

        task = self.task_trace_manager.create_task(
            user_id=user_id,
            conversation_id=conversation_id or (project_id or "raman-batch"),
            intent="raman_batch_analysis",
            input_message=f"批量分析 {len(files)} 个文件",
            input_files=files,
            project_id=project_id,
        )
        results: list[dict[str, Any]] = []
        success_count = 0
        failed_count = 0
        for file_item in files:
            child_task = self.task_trace_manager.create_task(
                user_id=user_id,
                conversation_id=conversation_id or (project_id or "raman-batch"),
                intent="raman_batch_item",
                input_message=f"批量子任务 {file_item.get('filename')}",
                input_files=[file_item],
                project_id=project_id,
            )
            file_result = self._analyze_single_file(file_item, user_id=user_id, project_id=project_id, options=options or {}, child_task_id=child_task["task_id"])
            results.append(file_result)
            if file_result["status"] == "success":
                success_count += 1
            else:
                failed_count += 1
        summary = {
            "total_files": len(files),
            "success_count": success_count,
            "failed_count": failed_count,
            "warning": failed_count > 0,
            "items": results,
        }
        csv_output = self._write_summary_csv(user_id, conversation_id or (project_id or "raman-batch"), summary, project_id=project_id)
        json_output = self.workspace_manager.save_output_file(
            user_id,
            conversation_id or (project_id or "raman-batch"),
            "batch_summary.json",
            __import__("json").dumps(summary, ensure_ascii=False, indent=2),
            project_id=project_id,
        )
        parent_status = "failed" if failed_count == len(files) else "success"
        self.task_trace_manager.update_task(
            task["task_id"],
            status=parent_status,
            progress=100,
            result_summary=summary,
            result_path=csv_output.get("path"),
            result_file_id=csv_output.get("file_id"),
        )
        return {
            "success": True,
            "task_id": task["task_id"],
            "summary": summary,
            "csv_file": csv_output,
            "json_file": json_output,
        }

    def get_batch_summary(self, task_id: str, *, user_id: str, is_admin: bool = False) -> dict[str, Any]:
        trace = self.task_trace_manager.get_task_trace(task_id, user_id=user_id, is_admin=is_admin)
        task = trace.get("task") or {}
        if str(task.get("task_type") or task.get("intent") or "") != "raman_batch_analysis":
            raise KeyError("该任务不是批量分析任务。")
        return dict(task.get("result_summary") or {})

    def _analyze_single_file(self, file_item: dict[str, Any], *, user_id: str, project_id: str | None, options: dict[str, Any], child_task_id: str) -> dict[str, Any]:
        source_path = (PROJECT_ROOT / str(file_item.get("path") or "")).resolve()
        try:
            result = predict_methanol(source_path)
            professional_analysis = analyze_spectrum_professionally(source_path, result)
            quality = professional_analysis.get("quality_analysis", {}) if professional_analysis.get("success") else {}
            peaks = ((professional_analysis.get("peak_analysis") or {}).get("peaks") or [])[:5]
            payload = {
                "file_id": file_item.get("file_id"),
                "filename": file_item.get("original_filename") or file_item.get("filename"),
                "status": "success",
                "quality_score": (quality.get("overall_quality") or quality.get("quality_level") or "unknown"),
                "prediction": result.get("final_prediction"),
                "unit": result.get("unit"),
                "major_peaks": [
                    {
                        "wavenumber": peak.get("wavenumber"),
                        "intensity": peak.get("intensity"),
                    }
                    for peak in peaks
                ],
                "error_message": None,
            }
            output_files: list[dict[str, Any]] = []
            if bool(options.get("generate_report")):
                exported = self.report_export_service.export_report(
                    user_id=user_id,
                    is_admin=False,
                    file_id=str(file_item.get("file_id") or ""),
                    project_id=project_id,
                    formats=list(options.get("export_formats") or ["markdown"]),
                )
                output_files.append({"path": exported["report"].get("markdown_path"), "filename": Path(str(exported["report"].get("markdown_path") or "")).name})
            self.task_trace_manager.record_skill_run(
                task_id=child_task_id,
                skill_name="raman_spectroscopy_skill",
                ability_name="predict_methanol_concentration",
                input_files=[file_item],
                output_files=output_files,
                status="success",
                raw_result_summary=f"预测值 {payload['prediction']}",
            )
            self.task_trace_manager.update_task(
                child_task_id,
                status="success",
                progress=100,
                file_id=file_item.get("file_id"),
                result_summary=payload,
            )
            return payload
        except Exception as exc:
            message = str(exc)
            payload = {
                "file_id": file_item.get("file_id"),
                "filename": file_item.get("original_filename") or file_item.get("filename"),
                "status": "failed",
                "quality_score": None,
                "prediction": None,
                "unit": "",
                "major_peaks": [],
                "error_message": message,
            }
            self.task_trace_manager.record_skill_run(
                task_id=child_task_id,
                skill_name="raman_spectroscopy_skill",
                ability_name="predict_methanol_concentration",
                input_files=[file_item],
                output_files=[],
                status="failed",
                error_message=message,
                raw_result_summary=message,
            )
            self.task_trace_manager.update_task(
                child_task_id,
                status="failed",
                progress=100,
                file_id=file_item.get("file_id"),
                error_message=message,
                result_summary=payload,
            )
            return payload

    def _write_summary_csv(self, user_id: str, conversation_id: str, summary: dict[str, Any], *, project_id: str | None = None) -> dict[str, Any]:
        csv_lines = [
            ["文件名", "状态", "质量评分", "预测结果", "主要峰位", "错误信息"],
        ]
        for item in summary.get("items") or []:
            csv_lines.append(
                [
                    item.get("filename"),
                    item.get("status"),
                    item.get("quality_score"),
                    item.get("prediction"),
                    "；".join(f"{peak.get('wavenumber')}:{peak.get('intensity')}" for peak in (item.get("major_peaks") or [])),
                    item.get("error_message") or "",
                ]
            )
        path = self.workspace_manager.get_workspace_path(user_id, conversation_id) / "outputs" / f"batch_summary_{summary.get('total_files', 0)}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerows(csv_lines)
        return self.workspace_manager.register_existing_file(
            user_id,
            conversation_id,
            path,
            original_name=path.name,
            kind="output",
            project_id=project_id,
        )
