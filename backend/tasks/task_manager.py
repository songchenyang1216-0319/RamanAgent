from __future__ import annotations

import json
import traceback
from threading import Lock
from typing import Any
from uuid import uuid4

from backend.repositories.base import dumps_json, now_iso
from backend.repositories.task_repository import TaskRepository
from backend.tasks.task_queue import LocalTaskQueue
from backend.tasks.task_schema import TaskCreateRequest, TaskEvent


class TaskManager:
    """A small local async task manager with a future Celery-compatible shape."""

    def __init__(self, repository: TaskRepository | None = None, queue: LocalTaskQueue | None = None) -> None:
        self.repository = repository or TaskRepository()
        self.queue = queue or LocalTaskQueue()
        self._events: dict[str, list[dict[str, Any]]] = {}
        self._cancelled: set[str] = set()
        self._lock = Lock()

    def create_task(self, request: TaskCreateRequest) -> dict[str, Any]:
        task_id = uuid4().hex
        payload = self.repository.create_task(
            {
                "task_id": task_id,
                "user_id": request.user_id or "default_user",
                "project_id": request.project_id,
                "conversation_id": request.conversation_id,
                "task_type": request.task_type,
                "status": "pending",
                "progress": 0,
                "current_step": "排队中",
                "payload_json": request.payload,
                "result_json": {},
                "artifacts_json": [],
            }
        )
        self.emit(task_id, "task_created", "任务已创建。", {"task_type": request.task_type})
        self.queue.submit(task_id, lambda: self._run_task(task_id, request))
        return self._public_task(payload)

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        task = self.repository.get_task_with_steps(task_id)
        return self._public_task(task) if task else None

    def list_tasks(self, user_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        return [self._public_task(item) for item in self.repository.list(user_id=user_id, limit=limit)]

    def cancel_task(self, task_id: str) -> dict[str, Any] | None:
        task = self.repository.get(task_id)
        if task is None:
            return None
        with self._lock:
            self._cancelled.add(task_id)
        cancelled_future = self.queue.cancel(task_id)
        updated = self.repository.update(
            task_id,
            status="cancelled",
            progress=100,
            current_step="已取消",
            finished_at=now_iso(),
            error_message="任务已取消。",
        )
        self.emit(task_id, "task_cancelled", "任务已取消。", {"future_cancelled": cancelled_future})
        return self._public_task(updated)

    def task_events(self, task_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._events.get(task_id) or [])

    def emit(self, task_id: str, event: str, content: str, data: dict[str, Any] | None = None) -> None:
        payload = TaskEvent.create(task_id, event, content, data).to_dict()
        with self._lock:
            self._events.setdefault(task_id, []).append(payload)
            self._events[task_id] = self._events[task_id][-200:]
        self.repository.add_event_step(task_id, event, {"content": content, **dict(data or {})}, status="done")

    def _run_task(self, task_id: str, request: TaskCreateRequest) -> None:
        try:
            self.repository.update(task_id, status="running", progress=5, current_step="任务启动", started_at=now_iso())
            self.emit(task_id, "task_started", "任务开始执行。")
            result = self._dispatch(request, task_id)
            if self._is_cancelled(task_id):
                self.repository.update(task_id, status="cancelled", progress=100, current_step="已取消", finished_at=now_iso(), error_message="任务已取消。")
                self.emit(task_id, "task_cancelled", "任务已取消。")
                return
            artifacts = result.get("artifacts") or result.get("output_files") or []
            self.repository.update(
                task_id,
                status="succeeded",
                progress=100,
                current_step="执行完成",
                finished_at=now_iso(),
                result_json=dumps_json(result),
                artifacts_json=dumps_json(artifacts),
            )
            self.emit(task_id, "task_succeeded", "任务执行完成。", {"artifacts": artifacts})
        except Exception as exc:
            error_message = self._friendly_error(exc)
            self.repository.update(
                task_id,
                status="failed",
                progress=100,
                current_step="执行失败",
                finished_at=now_iso(),
                error_message=error_message,
                result_json=dumps_json({"error_type": type(exc).__name__, "traceback": traceback.format_exc(limit=8)}),
            )
            self.emit(task_id, "task_failed", error_message, {"error_type": type(exc).__name__})

    def _dispatch(self, request: TaskCreateRequest, task_id: str) -> dict[str, Any]:
        task_type = str(request.task_type or "").strip()
        payload = dict(request.payload or {})
        if task_type == "raman_pipeline":
            return self._run_raman_pipeline(payload, task_id)
        if task_type == "rag_rebuild":
            return self._run_rag_rebuild(payload, request, task_id)
        if task_type == "report_export":
            return self._run_report_export(payload, request, task_id)
        if task_type == "raman_batch_analysis":
            return self._run_batch_analysis(payload, request, task_id)
        if task_type == "ocr":
            return self._run_ocr(payload, request, task_id)
        if task_type in {"noop", "echo"}:
            self.emit(task_id, "task_progress", "已完成 echo 任务。", payload)
            return {"success": True, "message": payload.get("message") or "ok", "artifacts": []}
        raise ValueError(f"未知任务类型：{task_type}")

    def _run_raman_pipeline(self, payload: dict[str, Any], task_id: str) -> dict[str, Any]:
        from backend.raman_pipeline.pipeline_runner import RamanPipelineRunner
        from backend.raman_pipeline.pipeline_schema import PipelineRequest

        request_payload = dict(payload.get("pipeline_request") or payload)
        self.emit(task_id, "tool_start", "开始运行 Raman Pipeline。", {"tool_name": "raman_pipeline"})
        result = RamanPipelineRunner().run(PipelineRequest(**request_payload)).model_dump()
        self.emit(task_id, "artifact_created", "Pipeline 产物已生成。", {"artifacts": result.get("artifacts") or []})
        return {"success": bool(result.get("success")), "pipeline_result": result, "artifacts": result.get("artifacts") or []}

    def _run_rag_rebuild(self, payload: dict[str, Any], request: TaskCreateRequest, task_id: str) -> dict[str, Any]:
        from backend.services.rag import RAGService

        user_id = str(payload.get("user_id") or request.user_id or "default_user")
        conversation_id = str(payload.get("conversation_id") or request.conversation_id or "")
        self.emit(task_id, "tool_start", "开始重建 RAG 索引。", {"tool_name": "rag"})
        if conversation_id:
            return RAGService().rebuild_conversation_index(user_id, conversation_id)
        return RAGService().rebuild_all_indexes(user_id)

    def _run_report_export(self, payload: dict[str, Any], request: TaskCreateRequest, task_id: str) -> dict[str, Any]:
        from backend.services.report_export_service import ReportExportService

        self.emit(task_id, "tool_start", "开始导出报告。", {"tool_name": "report_tool"})
        return ReportExportService().export_report(
            user_id=str(request.user_id or payload.get("user_id") or "default_user"),
            is_admin=bool(payload.get("is_admin")),
            task_id=payload.get("task_id"),
            file_id=payload.get("file_id"),
            project_id=payload.get("project_id") or request.project_id,
            formats=list(payload.get("formats") or ["markdown"]),
            title=payload.get("title"),
        )

    def _run_batch_analysis(self, payload: dict[str, Any], request: TaskCreateRequest, task_id: str) -> dict[str, Any]:
        from backend.services.batch_analysis_service import BatchAnalysisService

        self.emit(task_id, "tool_start", "开始批量 Raman 分析。", {"tool_name": "raman_model"})
        return BatchAnalysisService().batch_analyze(
            user_id=str(request.user_id or payload.get("user_id") or "default_user"),
            conversation_id=payload.get("conversation_id") or request.conversation_id or payload.get("project_id") or "raman-batch",
            file_ids=list(payload.get("file_ids") or []),
            project_id=payload.get("project_id") or request.project_id,
            options=dict(payload.get("options") or {}),
            is_admin=bool(payload.get("is_admin")),
        )

    def _run_ocr(self, payload: dict[str, Any], request: TaskCreateRequest, task_id: str) -> dict[str, Any]:
        from backend.services.file_service import FileCatalogService
        from backend.services.ocr import OCRService
        from raman_core.methanol.config import PROJECT_ROOT

        file_id = str(payload.get("file_id") or "")
        user_id = str(request.user_id or payload.get("user_id") or "default_user")
        file_item = FileCatalogService().get_file_for_user(file_id, user_id=user_id, is_admin=bool(payload.get("is_admin")))
        if file_item is None:
            raise FileNotFoundError("文件不存在或无权访问。")
        source_path = (PROJECT_ROOT / str(file_item.get("path") or "")).resolve()
        self.emit(task_id, "tool_start", "开始 OCR 识别。", {"tool_name": "document_tool"})
        if source_path.suffix.lower() == ".pdf":
            result = OCRService().extract_pdf_text(source_path, page_range=payload.get("page_range"))
        else:
            result = OCRService().extract_image_text(source_path)
        return {"success": bool(result.get("success")), "ocr": result, "artifacts": []}

    def _is_cancelled(self, task_id: str) -> bool:
        with self._lock:
            return task_id in self._cancelled

    def _public_task(self, task: dict[str, Any] | None) -> dict[str, Any]:
        if not task:
            return {}
        payload = dict(task)
        for key in ("result_json", "artifacts_json", "payload_json"):
            value = payload.get(key)
            if isinstance(value, str):
                try:
                    payload[key.replace("_json", "")] = json.loads(value) if value else ([] if key == "artifacts_json" else {})
                except Exception:
                    payload[key.replace("_json", "")] = value
        return payload

    def _friendly_error(self, exc: Exception) -> str:
        text = str(exc)
        if isinstance(exc, FileNotFoundError):
            return f"文件不存在：{text}"
        if isinstance(exc, PermissionError):
            return f"权限不足：{text}"
        if "timeout" in text.lower() or "timed out" in text.lower():
            return "任务执行超时，请稍后重试或检查外部服务。"
        return text or "任务执行失败。"


_TASK_MANAGER: TaskManager | None = None


def get_task_manager() -> TaskManager:
    global _TASK_MANAGER
    if _TASK_MANAGER is None:
        _TASK_MANAGER = TaskManager()
    return _TASK_MANAGER

