"""API endpoints for the composable Raman Pipeline."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from backend.api.auth_dependencies import get_request_user_context
from backend.repositories.pipeline_run_repository import PipelineRunRepository
from backend.raman_pipeline.algorithm_registry import get_algorithm_registry
from backend.raman_pipeline.algorithm_schema import RamanPipelineError
from backend.raman_pipeline.pipeline_runner import RamanPipelineRunner
from backend.raman_pipeline.pipeline_schema import PipelineRequest
from backend.raman_pipeline.pipeline_store import PipelineStore
from backend.security.audit import record_audit_log
from backend.tasks import get_task_manager
from backend.tasks.task_schema import TaskCreateRequest
from raman_core.methanol.config import OUTPUT_DIR, PROJECT_ROOT, ensure_dirs


router = APIRouter(prefix="/api/raman", tags=["raman-pipeline"])
store = PipelineStore()
runner = RamanPipelineRunner(store=store)
pipeline_run_repository = PipelineRunRepository()


def _error(message: str, status_code: int = 400, suggestion: str = "") -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={
            "message": "Raman Pipeline 请求失败",
            "error_message": message,
            "suggestion": suggestion,
        },
    )


def _safe_filename(filename: str) -> str:
    name = Path(filename or "spectrum.csv").name
    stem = re.sub(r"[^0-9A-Za-z._-]+", "_", Path(name).stem).strip("._") or "spectrum"
    suffix = Path(name).suffix.lower() or ".csv"
    return f"{stem}{suffix}"


async def _request_to_pipeline_request(request: Request) -> PipelineRequest:
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        payload_text = str(form.get("payload") or "{}")
        try:
            payload = json.loads(payload_text) if payload_text.strip() else {}
        except json.JSONDecodeError as exc:
            raise _error(f"Pipeline payload 不是合法 JSON：{exc}") from exc
        upload = form.get("file")
        if upload is not None and hasattr(upload, "filename"):
            filename = _safe_filename(str(upload.filename or "spectrum.csv"))
            if not filename.lower().endswith(".csv"):
                raise _error("文件格式错误：Raman Pipeline 只支持 CSV 文件。")
            ensure_dirs()
            upload_dir = OUTPUT_DIR / "raman_pipeline" / "uploads"
            upload_dir.mkdir(parents=True, exist_ok=True)
            path = upload_dir / f"{uuid.uuid4().hex[:10]}_{filename}"
            content = await upload.read()
            path.write_bytes(content)
            payload["file_path"] = str(path)
        return PipelineRequest(**payload)

    try:
        payload = await request.json()
    except Exception as exc:
        raise _error(f"请求体不是合法 JSON：{exc}") from exc
    return PipelineRequest(**(payload or {}))


@router.get("/algorithms")
def list_algorithms() -> dict[str, Any]:
    return {"success": True, **get_algorithm_registry().to_dict()}


@router.get("/algorithms/{algorithm_id}")
def get_algorithm(algorithm_id: str) -> dict[str, Any]:
    spec = get_algorithm_registry().get(algorithm_id)
    if spec is None:
        raise _error(f"未找到算法：{algorithm_id}", status_code=404)
    return {"success": True, "algorithm": spec.to_dict()}


@router.get("/pipeline/templates")
def list_templates() -> dict[str, Any]:
    return {"success": True, **store.list_templates()}


@router.post("/pipeline/validate")
async def validate_pipeline(request: Request) -> dict[str, Any]:
    try:
        pipeline_request = await _request_to_pipeline_request(request)
        result = runner.validate(pipeline_request)
        return {"success": bool(result.get("success")), **result}
    except HTTPException:
        raise
    except Exception as exc:
        raise _error(f"Pipeline 校验失败：{exc}") from exc


@router.post("/pipeline/run")
async def run_pipeline(
    request: Request,
    async_task: bool = Query(default=False),
    current_user: dict = Depends(get_request_user_context),
) -> dict[str, Any]:
    try:
        pipeline_request = await _request_to_pipeline_request(request)
        if not pipeline_request.file_path:
            raise RamanPipelineError("缺少 CSV 文件：请上传文件或在 JSON 中提供 file_path。")
        if async_task:
            task = get_task_manager().create_task(
                TaskCreateRequest(
                    task_type="raman_pipeline",
                    payload={"pipeline_request": pipeline_request.model_dump()},
                    user_id=current_user["user_id"],
                    conversation_id=str(request.query_params.get("conversation_id") or ""),
                    project_id=str(request.query_params.get("project_id") or "") or None,
                )
            )
            record_audit_log(
                user_id=current_user.get("user_id"),
                action="pipeline.run.async",
                resource_type="pipeline",
                resource_id=task.get("task_id"),
                request=request,
                detail={"template_id": pipeline_request.template_id, "file_path": pipeline_request.file_path},
            )
            return {"success": True, "async_task": True, "task_id": task.get("task_id"), "task": task}
        result = runner.run(pipeline_request)
        payload = result.model_dump()
        pipeline_run_repository.record_run(
            {
                "pipeline_run_id": payload.get("run_id"),
                "user_id": current_user.get("user_id"),
                "project_id": str(request.query_params.get("project_id") or "") or None,
                "conversation_id": str(request.query_params.get("conversation_id") or "") or None,
                "file_id": str(request.query_params.get("file_id") or "") or None,
                "pipeline_name": pipeline_request.template_id or "custom_pipeline",
                "pipeline_request": pipeline_request.model_dump(),
                "pipeline_result": payload,
                "status": "succeeded" if payload.get("success") else "failed",
                "elapsed_ms": int(payload.get("elapsed_ms") or 0),
                "artifacts": payload.get("artifacts") or [],
            }
        )
        record_audit_log(
            user_id=current_user.get("user_id"),
            action="pipeline.run",
            resource_type="pipeline",
            resource_id=payload.get("run_id"),
            request=request,
            detail={"success": payload.get("success"), "template_id": pipeline_request.template_id},
        )
        return payload
    except HTTPException:
        raise
    except RamanPipelineError as exc:
        raise _error(str(exc)) from exc
    except Exception as exc:
        raise _error(f"Pipeline 运行失败：{exc}") from exc


@router.get("/pipeline/history")
def list_history(limit: int = 30) -> dict[str, Any]:
    return {"success": True, **store.list_history(limit=limit)}
