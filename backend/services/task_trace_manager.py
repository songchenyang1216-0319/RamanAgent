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
    status: str
    input_message: str
    input_files: list[dict[str, Any]] = field(default_factory=list)
    output_files: list[dict[str, Any]] = field(default_factory=list)
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
    input_files: list[dict[str, Any]] = field(default_factory=list)
    output_files: list[dict[str, Any]] = field(default_factory=list)
    status: str = "success"
    started_at: str = field(default_factory=now_iso)
    finished_at: str | None = None
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
    ) -> dict[str, Any]:
        workspace = self.workspace_manager.create_workspace(user_id, conversation_id)
        task = Task(
            task_id=uuid4().hex,
            user_id=workspace["user_id"],
            conversation_id=workspace["conversation_id"],
            intent=str(intent or "unknown"),
            status="running",
            input_message=str(input_message or ""),
            input_files=list(input_files or []),
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
    ) -> dict[str, Any]:
        user_id, conversation_id = self._resolve_task_location(task_id)
        now = now_iso()
        run = SkillRun(
            run_id=uuid4().hex,
            task_id=task_id,
            skill_name=str(skill_name or ""),
            ability_name=ability_name,
            input_files=list(input_files or []),
            output_files=list(output_files or []),
            status=str(status or "success"),
            started_at=now,
            finished_at=now,
            error_message=error_message,
            raw_result_summary=(str(raw_result_summary or "")[:1000] or None),
        )
        payload = asdict(run)
        self._append_workspace_jsonl(user_id, conversation_id, "skill_runs.jsonl", payload)
        self.update_task(
            task_id,
            selected_skill=skill_name,
            selected_ability=ability_name,
            output_files=list(output_files or []),
            status="failed" if status == "failed" else "success",
            error_message=error_message,
        )
        if status == "failed" or error_message:
            self.workspace_manager.append_error(user_id, conversation_id, {"task_id": task_id, "skill_run": payload, "error_message": error_message})
        return payload

    def get_task_trace(self, task_id: str) -> dict[str, Any]:
        user_id, conversation_id = self._resolve_task_location(task_id)
        state = self.workspace_manager.read_task_state(user_id, conversation_id)
        task = next((item for item in state.get("tasks", []) if item.get("task_id") == task_id), None)
        if task is None:
            raise KeyError(f"未找到任务: {task_id}")
        return {
            "task": task,
            "steps": self._read_steps(user_id, conversation_id, task_id),
            "skill_runs": self._read_skill_runs(user_id, conversation_id, task_id),
        }

    def list_conversation_tasks(self, user_id: str | None, conversation_id: str | None) -> list[dict[str, Any]]:
        state = self.workspace_manager.read_task_state(user_id, conversation_id)
        return list(state.get("tasks") or [])

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
        return [item for item in self._read_workspace_jsonl(user_id, conversation_id, "skill_runs.jsonl") if item.get("task_id") == task_id]

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
