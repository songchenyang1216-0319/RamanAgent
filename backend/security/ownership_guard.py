from __future__ import annotations

from typing import Any, Callable

from fastapi import HTTPException

from backend.agent.session_store import get_session
from backend.repositories.task_repository import TaskRepository
from backend.security.audit_service import AuditService
from backend.security.resource_scope import ResourceScope
from backend.services.file_service import FileCatalogService


class OwnershipGuard:
    def __init__(self, audit_service: AuditService | None = None) -> None:
        self.audit_service = audit_service or AuditService()

    def _require_owner(
        self,
        *,
        scope: ResourceScope,
        resource_type: str,
        resource_id: str,
        owner_user_id: str | None,
        not_found_message: str = "资源不存在。",
        forbidden_message: str = "无权访问该资源。",
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not owner_user_id:
            raise HTTPException(status_code=404, detail=not_found_message)
        if scope.is_admin:
            if str(owner_user_id) != str(scope.user_id):
                self.audit_service.record(
                    user_id=scope.user_id,
                    action="admin.cross_user_access",
                    resource_type=resource_type,
                    resource_id=resource_id,
                    detail={
                        "owner_user_id": owner_user_id,
                        "reason": scope.reason or "admin_access",
                        "trace_id": scope.trace_id,
                    },
                )
            return dict(payload or {})
        if str(owner_user_id) != str(scope.user_id):
            raise HTTPException(status_code=403, detail=forbidden_message)
        return dict(payload or {})

    def require_conversation_owner(self, conversation_id: str, scope: ResourceScope) -> dict[str, Any]:
        session = get_session(conversation_id)
        if session is None or bool(session.get("is_deleted")):
            raise HTTPException(status_code=404, detail="会话不存在。")
        return self._require_owner(
            scope=scope,
            resource_type="conversation",
            resource_id=conversation_id,
            owner_user_id=str(session.get("user_id") or ""),
            not_found_message="会话不存在。",
            forbidden_message="无权访问该会话。",
            payload=session,
        )

    def require_file_owner(self, file_id: str, scope: ResourceScope, file_catalog: FileCatalogService | None = None) -> dict[str, Any]:
        catalog = file_catalog or FileCatalogService()
        file_item = catalog.get_file(file_id)
        if file_item is None:
            raise HTTPException(status_code=404, detail="文件不存在。")
        if not scope.is_admin and str(file_item.get("user_id") or "") != str(scope.user_id):
            raise HTTPException(status_code=404, detail="文件不存在。")
        return self._require_owner(
            scope=scope,
            resource_type="file",
            resource_id=file_id,
            owner_user_id=str(file_item.get("user_id") or ""),
            not_found_message="文件不存在。",
            forbidden_message="无权访问该文件。",
            payload=file_item,
        )

    def require_task_owner(self, task_id: str, scope: ResourceScope) -> dict[str, Any]:
        task = TaskRepository().get_task_with_steps(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail={"error_code": "TASK_NOT_FOUND", "error_message": "任务不存在。"})
        return self._require_owner(
            scope=scope,
            resource_type="task",
            resource_id=task_id,
            owner_user_id=str(task.get("user_id") or ""),
            not_found_message="任务不存在。",
            forbidden_message="无权访问该任务。",
            payload=task,
        )

    def require_project_owner(self, project_id: str, scope: ResourceScope, loader: Callable[[str], dict[str, Any] | None] | None = None) -> dict[str, Any]:
        project = loader(project_id) if loader else None
        if project is None:
            raise HTTPException(status_code=404, detail="项目不存在。")
        return self._require_owner(scope=scope, resource_type="project", resource_id=project_id, owner_user_id=str(project.get("user_id") or ""), payload=project)

    def require_workspace_owner(self, workspace_id: str, scope: ResourceScope) -> dict[str, Any]:
        return self._require_owner(scope=scope, resource_type="workspace", resource_id=workspace_id, owner_user_id=scope.user_id, payload={"workspace_id": workspace_id})

    def require_knowledge_base_owner(self, knowledge_base_id: str, scope: ResourceScope, owner_user_id: str | None = None) -> dict[str, Any]:
        return self._require_owner(scope=scope, resource_type="knowledge_base", resource_id=knowledge_base_id, owner_user_id=owner_user_id or scope.user_id, payload={"knowledge_base_id": knowledge_base_id})

    def require_report_owner(self, report_id: str, scope: ResourceScope, owner_user_id: str | None = None) -> dict[str, Any]:
        return self._require_owner(scope=scope, resource_type="report", resource_id=report_id, owner_user_id=owner_user_id or scope.user_id, payload={"report_id": report_id})

    def require_pipeline_run_owner(self, pipeline_run_id: str, scope: ResourceScope, owner_user_id: str | None = None) -> dict[str, Any]:
        return self._require_owner(scope=scope, resource_type="pipeline_run", resource_id=pipeline_run_id, owner_user_id=owner_user_id or scope.user_id, payload={"pipeline_run_id": pipeline_run_id})

    def require_rag_query_owner(self, rag_query_id: str, scope: ResourceScope, owner_user_id: str | None = None) -> dict[str, Any]:
        return self._require_owner(scope=scope, resource_type="rag_query", resource_id=rag_query_id, owner_user_id=owner_user_id or scope.user_id, payload={"rag_query_id": rag_query_id})


ownership_guard = OwnershipGuard()
