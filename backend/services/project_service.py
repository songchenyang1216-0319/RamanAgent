"""项目中心服务。"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.services.file_service import FileCatalogService
from backend.services.task_trace_manager import TaskTraceManager
from backend.services.workspace_manager import now_iso, read_json, write_json
from raman_core.methanol.config import PROJECT_ROOT


PROJECTS_PATH = PROJECT_ROOT / "storage" / "projects.json"


class ProjectService:
    def __init__(
        self,
        projects_path: Path | None = None,
        *,
        file_catalog: FileCatalogService | None = None,
        task_trace_manager: TaskTraceManager | None = None,
        report_service: Any | None = None,
    ) -> None:
        self.projects_path = Path(projects_path) if projects_path is not None else PROJECTS_PATH
        self.file_catalog = file_catalog or FileCatalogService()
        self.task_trace_manager = task_trace_manager or TaskTraceManager()
        self.report_service = report_service

    def list_projects(self, user_id: str, *, include_archived: bool = False) -> list[dict[str, Any]]:
        items = []
        for item in self._load_items():
            if str(item.get("user_id") or "") != str(user_id):
                continue
            if not include_archived and bool(item.get("archived")):
                continue
            items.append(self._enrich_counts(item))
        items.sort(key=lambda value: str(value.get("updated_at") or ""), reverse=True)
        return items

    def create_project(self, user_id: str, name: str, description: str | None = None) -> dict[str, Any]:
        cleaned_name = str(name or "").strip()
        if not cleaned_name:
            raise ValueError("项目名称不能为空。")
        item = {
            "project_id": uuid4().hex,
            "user_id": user_id,
            "name": cleaned_name,
            "description": str(description or "").strip(),
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "archived": False,
        }
        items = self._load_items()
        items.append(item)
        self._save_items(items)
        return self._enrich_counts(item)

    def get_project(self, project_id: str, *, user_id: str, is_admin: bool = False) -> dict[str, Any] | None:
        for item in self._load_items():
            if str(item.get("project_id") or "") != str(project_id):
                continue
            if is_admin or str(item.get("user_id") or "") == str(user_id):
                return self._enrich_counts(item)
            return None
        return None

    def update_project(self, project_id: str, *, user_id: str, name: str | None = None, description: str | None = None, is_admin: bool = False) -> dict[str, Any]:
        items = self._load_items()
        target = next((item for item in items if str(item.get("project_id") or "") == str(project_id)), None)
        if target is None:
            raise KeyError("项目不存在。")
        if not is_admin and str(target.get("user_id") or "") != str(user_id):
            raise PermissionError("无权修改该项目。")
        if name is not None:
            cleaned_name = str(name or "").strip()
            if not cleaned_name:
                raise ValueError("项目名称不能为空。")
            target["name"] = cleaned_name
        if description is not None:
            target["description"] = str(description or "").strip()
        target["updated_at"] = now_iso()
        self._save_items(items)
        return self._enrich_counts(target)

    def archive_project(self, project_id: str, *, user_id: str, is_admin: bool = False) -> dict[str, Any]:
        items = self._load_items()
        target = next((item for item in items if str(item.get("project_id") or "") == str(project_id)), None)
        if target is None:
            raise KeyError("项目不存在。")
        if not is_admin and str(target.get("user_id") or "") != str(user_id):
            raise PermissionError("无权删除该项目。")
        target["archived"] = True
        target["updated_at"] = now_iso()
        self._save_items(items)
        return self._enrich_counts(target)

    def attach_file(self, project_id: str, file_id: str, *, user_id: str, is_admin: bool = False) -> dict[str, Any]:
        project = self.get_project(project_id, user_id=user_id, is_admin=is_admin)
        if project is None:
            raise KeyError("项目不存在。")
        updated_file = self.file_catalog.update_file_project(file_id, project_id, user_id=user_id, is_admin=is_admin)
        return {
            "project": project,
            "file": updated_file,
        }

    def list_project_files(self, project_id: str, *, user_id: str, is_admin: bool = False) -> list[dict[str, Any]]:
        project = self.get_project(project_id, user_id=user_id, is_admin=is_admin)
        if project is None:
            raise KeyError("项目不存在。")
        if is_admin:
            return self.file_catalog.list_files(project_id=project_id)
        return self.file_catalog.list_files(user_id=user_id, project_id=project_id)

    def list_project_tasks(self, project_id: str, *, user_id: str, is_admin: bool = False) -> list[dict[str, Any]]:
        project = self.get_project(project_id, user_id=user_id, is_admin=is_admin)
        if project is None:
            raise KeyError("项目不存在。")
        tasks = self.task_trace_manager.list_tasks(None if is_admin else user_id)
        return [item for item in tasks if str(item.get("project_id") or "") == str(project_id)]

    def list_project_reports(self, project_id: str, *, user_id: str, is_admin: bool = False) -> list[dict[str, Any]]:
        project = self.get_project(project_id, user_id=user_id, is_admin=is_admin)
        if project is None:
            raise KeyError("项目不存在。")
        if self.report_service is None:
            return []
        return self.report_service.list_reports(None if is_admin else user_id, project_id=project_id, is_admin=is_admin)

    def _enrich_counts(self, item: dict[str, Any]) -> dict[str, Any]:
        payload = dict(item or {})
        user_id = str(payload.get("user_id") or "")
        project_id = str(payload.get("project_id") or "")
        payload["file_count"] = len(self.file_catalog.list_files(user_id=user_id, project_id=project_id))
        payload["task_count"] = len([task for task in self.task_trace_manager.list_tasks(user_id) if str(task.get("project_id") or "") == project_id])
        if self.report_service is not None:
            payload["report_count"] = len(self.report_service.list_reports(user_id, project_id=project_id))
        else:
            payload["report_count"] = 0
        return payload

    def _load_items(self) -> list[dict[str, Any]]:
        value = read_json(self.projects_path, [])
        return value if isinstance(value, list) else []

    def _save_items(self, items: list[dict[str, Any]]) -> None:
        write_json(self.projects_path, items)
