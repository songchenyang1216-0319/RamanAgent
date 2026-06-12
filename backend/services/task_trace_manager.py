"""Task, step, and SkillRun tracing for Agent workflows."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.services.workspace_manager import WorkspaceManager, now_iso, read_json, write_json
from raman_core.methanol.config import PROJECT_ROOT


TASK_INDEX_PATH = PROJECT_ROOT / "storage" / "task_index.json"


@dataclass
class Task:
    task_id: str
    user_id: str
    conversation_id: str
    intent: str
    task_type: str
    status: str
    progress: int
    input_message: str
    input_files: list[dict[str, Any]] = field(default_factory=list)
    output_files: list[dict[str, Any]] = field(default_factory=list)
    project_id: str | None = None
    file_id: str | None = None
    result_path: str | None = None
    result_file_id: str | None = None
    result_summary: dict[str, Any] | None = None
    selected_skill: str | None = None
    selected_ability: str | None = None
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    error_message: str | None = None


@dataclass
class TaskStep:
    step_id: str
    task_id: str
    step_index: int
    name: str
    status: str
    detail: dict[str, Any] | None = None
    started_at: str = field(default_factory=now_iso)
    finished_at: str | None = None
    error_message: str | None = None


@dataclass
class SkillRun:
    run_id: str
    task_id: str
    skill_name: str
    ability_name: str | None
    capability: str | None = None
    input_summary: str | None = None
    input_files: list[dict[str, Any]] = field(default_factory=list)
    output_files: list[dict[str, Any]] = field(default_factory=list)
    status: str = "success"
    started_at: str = field(default_factory=now_iso)
    finished_at: str | None = None
    ended_at: str | None = None
    duration_ms: int = 0
    error_message: str | None = None
    raw_result_summary: str | None = None


class TaskTraceManager:
    """Persist task traces into workspace context and JSONL logs."""

    def __init__(self, workspace_manager: WorkspaceManager | None = None) -> None:
        self.workspace_manager = workspace_manager or WorkspaceManager()

    def create_task(
        self,
        user_id: str | None,
        conversation_id: str | None,
        intent: str,
        input_message: str,
        input_files: list[dict[str, Any]] | None = None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        workspace = self.workspace_manager.create_workspace(user_id, conversation_id)
        task = Task(
            task_id=uuid4().hex,
            user_id=workspace["user_id"],
            conversation_id=workspace["conversation_id"],
            intent=str(intent or "unknown"),
            task_type=str(intent or "unknown"),
            project_id=project_id,
            status="running",
            progress=5,
            input_message=str(input_message or ""),
            input_files=list(input_files or []),
            file_id=self._extract_primary_file_id(input_files or []),
        )
        payload = asdict(task)
        state = self.workspace_manager.read_task_state(task.user_id, task.conversation_id)
        tasks = [item for item in state.get("tasks", []) if item.get("task_id") != task.task_id]
        tasks.append(payload)
        state["tasks"] = tasks
        state["current_task_id"] = task.task_id
        self.workspace_manager.update_task_state(task.user_id, task.conversation_id, state)
        self._update_index(task.task_id, task.user_id, task.conversation_id)
        return payload

    def update_task(self, task_id: str, **kwargs: Any) -> dict[str, Any]:
        user_id, conversation_id = self._resolve_task_location(task_id)
        state = self.workspace_manager.read_task_state(user_id, conversation_id)
        tasks = list(state.get("tasks") or [])
        task = next((item for item in tasks if item.get("task_id") == task_id), None)
        if task is None:
            raise KeyError(f"未找到任务: {task_id}")
        for key, value in kwargs.items():
            if key in Task.__dataclass_fields__:
                task[key] = value
        task["updated_at"] = now_iso()
        if task.get("status") == "failed" and task.get("error_message"):
            self.workspace_manager.append_error(user_id, conversation_id, {"task_id": task_id, "error_message": task["error_message"]})
        task["task_type"] = task.get("task_type") or task.get("intent") or "unknown"
        task["progress"] = self._normalize_progress(task.get("status"), task.get("progress"))
        self.workspace_manager.update_task_state(user_id, conversation_id, state)
        return task

    def add_step(self, task_id: str, name: str, status: str = "running", detail: dict[str, Any] | None = None) -> dict[str, Any]:
        user_id, conversation_id = self._resolve_task_location(task_id)
        existing_steps = self._read_steps(user_id, conversation_id, task_id)
        step = TaskStep(
            step_id=uuid4().hex,
            task_id=task_id,
            step_index=len(existing_steps) + 1,
            name=str(name or "step"),
            status=str(status or "running"),
            detail=detail or {},
        )
        payload = asdict(step)
        self._append_workspace_jsonl(user_id, conversation_id, "task_steps.jsonl", payload)
        self.update_task(task_id, status="running", progress=min(95, 10 + len(existing_steps) * 15))
        return payload

    def finish_step(self, step_id: str, status: str = "success", detail: dict[str, Any] | None = None, error_message: str | None = None) -> dict[str, Any]:
        user_id, conversation_id, step = self._resolve_step(step_id)
        finished = dict(step)
        finished.update(
            {
                "status": status,
                "detail": detail if detail is not None else step.get("detail"),
                "finished_at": now_iso(),
                "error_message": error_message,
            }
        )
        self._append_workspace_jsonl(user_id, conversation_id, "task_steps.jsonl", finished)
        if status == "failed" or error_message:
            self.workspace_manager.append_error(user_id, conversation_id, {"step_id": step_id, "task_id": step.get("task_id"), "error_message": error_message})
            self.update_task(step.get("task_id"), status="failed", progress=self._normalize_progress("failed", 100), error_message=error_message)
        return finished

    def record_skill_run(
        self,
        task_id: str,
        skill_name: str,
        ability_name: str | None,
        input_files: list[dict[str, Any]] | None,
        output_files: list[dict[str, Any]] | None,
        status: str,
        error_message: str | None = None,
        raw_result_summary: str | None = None,
        input_summary: str | None = None,
    ) -> dict[str, Any]:
        user_id, conversation_id = self._resolve_task_location(task_id)
        now = now_iso()
        normalized_output_files = self._normalize_output_files(user_id, conversation_id, output_files or [])
        run = SkillRun(
            run_id=uuid4().hex,
            task_id=task_id,
            skill_name=str(skill_name or ""),
            ability_name=ability_name,
            capability=ability_name,
            input_summary=input_summary or self._build_input_summary(input_files or []),
            input_files=list(input_files or []),
            output_files=normalized_output_files,
            status=str(status or "success"),
            started_at=now,
            finished_at=now,
            ended_at=now,
            duration_ms=0,
            error_message=error_message,
            raw_result_summary=(str(raw_result_summary or "")[:1000] or None),
        )
        payload = asdict(run)
        self._append_workspace_jsonl(user_id, conversation_id, "skill_runs.jsonl", payload)
        self.update_task(
            task_id,
            selected_skill=skill_name,
            selected_ability=ability_name,
            output_files=normalized_output_files,
            result_path=self._extract_result_path(normalized_output_files),
            result_file_id=self._extract_primary_file_id(normalized_output_files),
            status="failed" if status == "failed" else "success",
            progress=self._normalize_progress("failed" if status == "failed" else "success", 100),
            error_message=error_message,
        )
        if status == "failed" or error_message:
            self.workspace_manager.append_error(user_id, conversation_id, {"task_id": task_id, "skill_run": payload, "error_message": error_message})
        return payload

    def get_task_trace(self, task_id: str, *, user_id: str | None = None, is_admin: bool = False) -> dict[str, Any]:
        owner_user_id, conversation_id = self._resolve_task_location(task_id)
        if user_id is not None and not is_admin and str(owner_user_id) != str(user_id):
            raise PermissionError("无权访问该任务。")
        state = self.workspace_manager.read_task_state(owner_user_id, conversation_id)
        task = next((item for item in state.get("tasks", []) if item.get("task_id") == task_id), None)
        if task is None:
            raise KeyError(f"未找到任务: {task_id}")
        return {
            "task": task,
            "steps": self._read_steps(owner_user_id, conversation_id, task_id),
            "skill_runs": self._read_skill_runs(owner_user_id, conversation_id, task_id),
        }

    def list_conversation_tasks(self, user_id: str | None, conversation_id: str | None) -> list[dict[str, Any]]:
        state = self.workspace_manager.read_task_state(user_id, conversation_id)
        tasks = [self._enrich_task(item) for item in list(state.get("tasks") or [])]
        tasks.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        return tasks

    def list_tasks(self, user_id: str | None = None, conversation_id: str | None = None) -> list[dict[str, Any]]:
        index = read_json(TASK_INDEX_PATH, {})
        if not isinstance(index, dict):
            return []
        tasks: list[dict[str, Any]] = []
        for task_id, location in index.items():
            if not isinstance(location, dict):
                continue
            current_user_id = str(location.get("user_id") or "")
            current_conversation_id = str(location.get("conversation_id") or "")
            if user_id and current_user_id != str(user_id):
                continue
            if conversation_id and current_conversation_id != str(conversation_id):
                continue
            try:
                trace = self.get_task_trace(task_id)
            except KeyError:
                continue
            tasks.append(self._enrich_task(trace.get("task") or {}))
        tasks.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        return tasks

    def get_task_logs(self, task_id: str, *, user_id: str | None = None, is_admin: bool = False) -> dict[str, Any]:
        trace = self.get_task_trace(task_id, user_id=user_id, is_admin=is_admin)
        task = trace.get("task") or {}
        return {
            "task_id": task_id,
            "steps": trace.get("steps") or [],
            "skill_runs": trace.get("skill_runs") or [],
        }

    def get_task_result(self, task_id: str, *, user_id: str | None = None, is_admin: bool = False) -> dict[str, Any]:
        trace = self.get_task_trace(task_id, user_id=user_id, is_admin=is_admin)
        task = trace.get("task") or {}
        return {
            "task_id": task_id,
            "result_path": task.get("result_path"),
            "result_file_id": task.get("result_file_id"),
            "result_download_url": self._build_result_download_url(task),
            "result_summary": task.get("result_summary"),
            "status": task.get("status"),
        }

    def list_skill_logs(self, user_id: str | None = None, conversation_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        index = read_json(TASK_INDEX_PATH, {})
        if not isinstance(index, dict):
            return []
        logs: list[dict[str, Any]] = []
        for task_id, location in index.items():
            if not isinstance(location, dict):
                continue
            current_user_id = str(location.get("user_id") or "")
            current_conversation_id = str(location.get("conversation_id") or "")
            if user_id and current_user_id != str(user_id):
                continue
            if conversation_id and current_conversation_id != str(conversation_id):
                continue
            for item in self._read_skill_runs(current_user_id, current_conversation_id, task_id):
                item = dict(item)
                item.setdefault("capability", item.get("ability_name"))
                item.setdefault("ended_at", item.get("finished_at"))
                item.setdefault("duration_ms", 0)
                logs.append(item)
        logs.sort(key=lambda item: str(item.get("started_at") or ""), reverse=True)
        return logs[: max(1, int(limit))]

    def _workspace_log_path(self, user_id: str, conversation_id: str, filename: str) -> Path:
        workspace_path = self.workspace_manager.get_workspace_path(user_id, conversation_id)
        return workspace_path / "logs" / filename

    def _append_workspace_jsonl(self, user_id: str, conversation_id: str, filename: str, payload: dict[str, Any]) -> None:
        path = self._workspace_log_path(user_id, conversation_id, filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _read_workspace_jsonl(self, user_id: str, conversation_id: str, filename: str) -> list[dict[str, Any]]:
        path = self._workspace_log_path(user_id, conversation_id, filename)
        if not path.exists():
            return []
        items: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except Exception:
                continue
            if isinstance(value, dict):
                items.append(value)
        return items

    def _read_steps(self, user_id: str, conversation_id: str, task_id: str) -> list[dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for item in self._read_workspace_jsonl(user_id, conversation_id, "task_steps.jsonl"):
            if item.get("task_id") != task_id:
                continue
            step_id = str(item.get("step_id") or "")
            if step_id:
                latest[step_id] = item
        return sorted(latest.values(), key=lambda item: int(item.get("step_index") or 0))

    def _read_skill_runs(self, user_id: str, conversation_id: str, task_id: str) -> list[dict[str, Any]]:
        return [self._enrich_skill_run(item) for item in self._read_workspace_jsonl(user_id, conversation_id, "skill_runs.jsonl") if item.get("task_id") == task_id]

    def _resolve_step(self, step_id: str) -> tuple[str, str, dict[str, Any]]:
        index = read_json(TASK_INDEX_PATH, {})
        if not isinstance(index, dict):
            index = {}
        for task_id, location in index.items():
            user_id = location.get("user_id")
            conversation_id = location.get("conversation_id")
            if not user_id or not conversation_id:
                continue
            for step in self._read_steps(user_id, conversation_id, task_id):
                if step.get("step_id") == step_id:
                    return user_id, conversation_id, step
        raise KeyError(f"未找到步骤: {step_id}")

    def _resolve_task_location(self, task_id: str) -> tuple[str, str]:
        index = read_json(TASK_INDEX_PATH, {})
        location = index.get(task_id) if isinstance(index, dict) else None
        if not isinstance(location, dict):
            raise KeyError(f"未找到任务: {task_id}")
        return str(location["user_id"]), str(location["conversation_id"])

    def _update_index(self, task_id: str, user_id: str, conversation_id: str) -> None:
        index = read_json(TASK_INDEX_PATH, {})
        if not isinstance(index, dict):
            index = {}
        index[task_id] = {
            "user_id": user_id,
            "conversation_id": conversation_id,
            "updated_at": now_iso(),
        }
        write_json(TASK_INDEX_PATH, index)

    def _normalize_output_files(self, user_id: str, conversation_id: str, output_files: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for item in output_files:
            payload = dict(item or {})
            raw_path = payload.get("path")
            if not raw_path:
                normalized.append(payload)
                continue
            path = Path(str(raw_path))
            if not path.is_absolute():
                path = PROJECT_ROOT / str(raw_path)
            try:
                if path.exists() and path.is_file():
                    registered = self.workspace_manager.register_existing_file(
                        user_id,
                        conversation_id,
                        path,
                        original_name=payload.get("filename"),
                        kind="output",
                    )
                    normalized.append(registered)
                    continue
            except Exception:
                pass
            normalized.append(payload)
        return normalized

    def _extract_primary_file_id(self, items: list[dict[str, Any]]) -> str | None:
        for item in items:
            value = str((item or {}).get("file_id") or "").strip()
            if value:
                return value
        return None

    def _extract_result_path(self, items: list[dict[str, Any]]) -> str | None:
        for item in items:
            value = str((item or {}).get("path") or "").strip()
            if value:
                return value
        return None

    def _build_input_summary(self, input_files: list[dict[str, Any]]) -> str:
        names = []
        for item in input_files:
            name = str((item or {}).get("original_filename") or (item or {}).get("original_name") or (item or {}).get("filename") or "").strip()
            if name:
                names.append(name)
        return "、".join(names[:3]) or "无输入文件"

    def _normalize_progress(self, status: str | None, progress: Any) -> int:
        if str(status or "") == "success":
            return 100
        if str(status or "") == "failed":
            return 100
        try:
            value = int(progress)
        except Exception:
            value = 0
        return max(0, min(99, value))

    def _build_result_download_url(self, task: dict[str, Any]) -> str:
        result_file_id = str(task.get("result_file_id") or "").strip()
        if result_file_id:
            return f"/api/files/{result_file_id}/download"
        result_path = str(task.get("result_path") or "").replace("\\", "/")
        if result_path.startswith("outputs/reports/"):
            return f"/static/reports/{Path(result_path).name}"
        if result_path.startswith("outputs/figures/"):
            return f"/static/figures/{Path(result_path).name}"
        if result_path.startswith("workspace/"):
            return ""
        return ""

    def _enrich_task(self, task: dict[str, Any]) -> dict[str, Any]:
        payload = dict(task or {})
        payload["task_type"] = payload.get("task_type") or payload.get("intent") or "unknown"
        payload["progress"] = self._normalize_progress(payload.get("status"), payload.get("progress"))
        payload["file_id"] = payload.get("file_id") or self._extract_primary_file_id(payload.get("input_files") or [])
        payload["result_path"] = payload.get("result_path") or self._extract_result_path(payload.get("output_files") or [])
        payload["result_file_id"] = payload.get("result_file_id") or self._extract_primary_file_id(payload.get("output_files") or [])
        payload["result_download_url"] = self._build_result_download_url(payload)
        return payload

    def _enrich_skill_run(self, item: dict[str, Any]) -> dict[str, Any]:
        payload = dict(item or {})
        payload.setdefault("capability", payload.get("ability_name"))
        payload.setdefault("ended_at", payload.get("finished_at"))
        payload.setdefault("duration_ms", 0)
        return payload
