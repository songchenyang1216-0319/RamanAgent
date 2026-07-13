from __future__ import annotations

import json
import traceback
from threading import Lock
from typing import Any
from uuid import uuid4

from backend.repositories.base import dumps_json, now_iso
from backend.repositories.task_repository import TaskRepository
from backend.tasks.task_queue import TaskQueueBackend, create_task_queue_backend
from backend.tasks.task_schema import TaskCreateRequest, TaskEvent


class TaskManager:
    """A small local async task manager with a future Celery-compatible shape."""

    def __init__(self, repository: TaskRepository | None = None, queue: TaskQueueBackend | None = None) -> None:
        self.repository = repository or TaskRepository()
        self.queue = queue or create_task_queue_backend(repository=self.repository)
        self._events: dict[str, list[dict[str, Any]]] = {}
        self._cancelled: set[str] = set()
        self._lock = Lock()

    def create_task(self, request: TaskCreateRequest) -> dict[str, Any]:
        user_id = request.user_id or "default_user"
        idempotency_key = str(request.idempotency_key or "").strip() or None
        if idempotency_key:
            existing = self.repository.get_by_idempotency_key(user_id, idempotency_key)
            if existing is not None:
                return self._public_task(self.repository.get_task_with_steps(str(existing["task_id"])) or existing)
        task_id = uuid4().hex
        payload = self.repository.create_task(
            {
                "task_id": task_id,
                "user_id": user_id,
                "project_id": request.project_id,
                "conversation_id": request.conversation_id,
                "task_type": request.task_type,
                "status": "pending",
                "progress": 0,
                "current_step": "排队中",
                "attempt": 0,
                "max_attempts": max(1, int(request.max_attempts or 1)),
                "idempotency_key": idempotency_key,
                "cancel_requested": 0,
                "parent_task_id": request.parent_task_id,
                "trace_id": request.trace_id or uuid4().hex,
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
            cancel_requested=1,
            finished_at=now_iso(),
            error_message="任务已取消。",
        )
        self.emit(task_id, "task_cancelled", "任务已取消。", {"future_cancelled": cancelled_future})
        self.emit(task_id, "done", "任务事件流已结束。", {"status": "cancelled"})
        return self._public_task(updated)

    def task_events(self, task_id: str) -> list[dict[str, Any]]:
        return self.repository.list_task_events(task_id)

    def task_events_after(self, task_id: str, *, after_sequence: int = 0, last_event_id: str | None = None) -> list[dict[str, Any]]:
        sequence = int(after_sequence or 0)
        if last_event_id:
            sequence = max(sequence, self.repository.get_event_sequence(task_id, last_event_id))
        return self.repository.list_task_events(task_id, after_sequence=sequence)

    def emit(self, task_id: str, event: str, content: str, data: dict[str, Any] | None = None) -> None:
        task = self.repository.get(task_id) or {}
        event_payload = TaskEvent.create(
            task_id,
            event,
            content,
            data,
        ).to_dict()
        event_payload.update(
            {
                "content": content,
                "data": dict(data or {}),
                "task_id": task_id,
                "status": task.get("status"),
            }
        )
        persisted = self.repository.add_task_event(
            task_id,
            str(event_payload.get("event") or event),
            event_payload,
            conversation_id=task.get("conversation_id"),
            trace_id=task.get("trace_id"),
        )
        event_payload["sequence"] = persisted.get("sequence")
        event_payload["event_id"] = persisted.get("event_id", event_payload.get("event_id"))
        with self._lock:
            payload = event_payload
            self._events.setdefault(task_id, []).append(payload)
            self._events[task_id] = self._events[task_id][-200:]
        self.repository.add_event_step(task_id, event, {"content": content, **dict(data or {})}, status="done")

    def ensure_not_cancelled(self, task_id: str) -> None:
        task = self.repository.get(task_id) or {}
        if self._is_cancelled(task_id) or bool(task.get("cancel_requested")):
            raise InterruptedError("任务已请求取消。")

    def _run_task(self, task_id: str, request: TaskCreateRequest) -> None:
        try:
            current = self.repository.get(task_id) or {}
            if self._is_cancelled(task_id) or bool(current.get("cancel_requested")):
                self.repository.update(task_id, status="cancelled", progress=100, current_step="已取消", finished_at=now_iso(), error_message="任务已取消。")
                self.emit(task_id, "task_cancelled", "任务已取消。")
                return
            attempt = int(current.get("attempt") or 0) + 1
            self.repository.update(task_id, status="running", progress=5, current_step="任务启动", attempt=attempt, started_at=now_iso(), heartbeat_at=now_iso())
            self.emit(task_id, "task_started", "任务开始执行。")
            result = self._dispatch(request, task_id)
            if self._is_cancelled(task_id):
                self.repository.update(task_id, status="cancelled", progress=100, current_step="已取消", finished_at=now_iso(), error_message="任务已取消。")
                self.emit(task_id, "task_cancelled", "任务已取消。")
                self.emit(task_id, "done", "任务事件流已结束。", {"status": "cancelled"})
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
            self.emit(task_id, "final", "任务执行完成。", {"status": "succeeded", "result": result})
            self.emit(task_id, "done", "任务事件流已结束。", {"status": "succeeded"})
        except InterruptedError as exc:
            self.repository.update(task_id, status="cancelled", progress=100, current_step="已取消", finished_at=now_iso(), error_message=str(exc))
            self.emit(task_id, "task_cancelled", str(exc), {})
            self.emit(task_id, "done", "任务事件流已结束。", {"status": "cancelled"})
        except Exception as exc:
            error_message = self._friendly_error(exc)
            current = self.repository.get(task_id) or {}
            attempt = int(current.get("attempt") or 1)
            max_attempts = max(1, int(current.get("max_attempts") or request.max_attempts or 1))
            if attempt < max_attempts and not self._is_cancelled(task_id):
                self.repository.update(
                    task_id,
                    status="pending",
                    progress=0,
                    current_step="等待重试",
                    retry_at=now_iso(),
                    error_code=type(exc).__name__,
                    failed_reason=error_message,
                    error_message=error_message,
                )
                self.emit(task_id, "task_progress", "任务失败，已进入重试队列。", {"attempt": attempt, "max_attempts": max_attempts, "error_code": type(exc).__name__})
                self.queue.submit(task_id, lambda: self._run_task(task_id, request))
                return
            self.repository.update(
                task_id,
                status="failed",
                progress=100,
                current_step="执行失败",
                finished_at=now_iso(),
                error_message=error_message,
                error_code=type(exc).__name__,
                failed_reason=error_message,
                result_json=dumps_json({"error_type": type(exc).__name__, "traceback": traceback.format_exc(limit=8)}),
            )
            self.emit(task_id, "task_failed", error_message, {"error_type": type(exc).__name__})
            self.emit(task_id, "done", "任务事件流已结束。", {"status": "failed"})

    def _dispatch(self, request: TaskCreateRequest, task_id: str) -> dict[str, Any]:
        task_type = str(request.task_type or "").strip()
        payload = dict(request.payload or {})
        if task_type == "raman_pipeline":
            self.ensure_not_cancelled(task_id)
            return self._run_raman_pipeline(payload, task_id)
        if task_type == "rag_rebuild":
            self.ensure_not_cancelled(task_id)
            return self._run_rag_rebuild(payload, request, task_id)
        if task_type == "report_export":
            self.ensure_not_cancelled(task_id)
            return self._run_report_export(payload, request, task_id)
        if task_type == "raman_batch_analysis":
            self.ensure_not_cancelled(task_id)
            return self._run_batch_analysis(payload, request, task_id)
        if task_type == "ocr":
            self.ensure_not_cancelled(task_id)
            return self._run_ocr(payload, request, task_id)
        if task_type in {"noop", "echo"}:
            self.ensure_not_cancelled(task_id)
            self.emit(task_id, "task_progress", "已完成 echo 任务。", payload)
            return {"success": True, "message": payload.get("message") or "ok", "artifacts": []}
        raise ValueError(f"未知任务类型：{task_type}")

    def _run_raman_pipeline(self, payload: dict[str, Any], task_id: str) -> dict[str, Any]:
        from backend.raman_pipeline.pipeline_runner import RamanPipelineRunner
        from backend.raman_pipeline.pipeline_schema import PipelineRequest

        request_payload = dict(payload.get("pipeline_request") or payload)
        self.emit(task_id, "tool_start", "开始运行 Raman Pipeline。", {"tool_name": "raman_pipeline"})
        result = RamanPipelineRunner().run(
            PipelineRequest(**request_payload),
            cancellation_checker=lambda: self._is_cancelled(task_id) or bool((self.repository.get(task_id) or {}).get("cancel_requested")),
        ).model_dump()
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
