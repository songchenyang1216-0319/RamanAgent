"""报告注册与导出索引服务。"""

from __future__ import annotations

import csv
import json
import zipfile
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.services.file_service import FileCatalogService
from backend.services.workspace_manager import now_iso, read_json, write_json
from raman_core.methanol.config import OUTPUT_DIR, PROJECT_ROOT, REPORT_DIR


REPORTS_PATH = PROJECT_ROOT / "storage" / "reports.json"


class ReportRegistryService:
    def __init__(self, reports_path: Path | None = None, *, file_catalog: FileCatalogService | None = None) -> None:
        self.reports_path = Path(reports_path) if reports_path is not None else REPORTS_PATH
        self.file_catalog = file_catalog or FileCatalogService()

    def list_reports(self, user_id: str | None, *, project_id: str | None = None, is_admin: bool = False) -> list[dict[str, Any]]:
        items = []
        for item in self._load_items():
            if not is_admin and user_id and str(item.get("user_id") or "") != str(user_id):
                continue
            if project_id is not None and str(item.get("project_id") or "") != str(project_id):
                continue
            if bool(item.get("deleted")):
                continue
            items.append(dict(item))
        items.sort(key=lambda value: str(value.get("created_at") or ""), reverse=True)
        return items

    def get_report(self, report_id: str, *, user_id: str, is_admin: bool = False) -> dict[str, Any] | None:
        for item in self._load_items():
            if str(item.get("report_id") or "") != str(report_id):
                continue
            if bool(item.get("deleted")):
                return None
            if is_admin or str(item.get("user_id") or "") == str(user_id):
                return dict(item)
            return None
        return None

    def create_report_record(
        self,
        *,
        user_id: str,
        project_id: str | None,
        task_id: str | None,
        file_id: str | None,
        title: str,
        report_type: str,
        markdown_path: str | None,
        html_path: str | None,
        pdf_path: str | None,
        docx_path: str | None,
        json_path: str | None,
        status: str,
        error_message: str | None = None,
    ) -> dict[str, Any]:
        item = {
            "report_id": uuid4().hex,
            "user_id": user_id,
            "project_id": project_id,
            "task_id": task_id,
            "file_id": file_id,
            "title": title,
            "report_type": report_type,
            "created_at": now_iso(),
            "markdown_path": markdown_path,
            "html_path": html_path,
            "pdf_path": pdf_path,
            "docx_path": docx_path,
            "json_path": json_path,
            "status": status,
            "error_message": error_message,
            "deleted": False,
        }
        items = self._load_items()
        items.append(item)
        self._save_items(items)
        return dict(item)

    def delete_report(self, report_id: str, *, user_id: str, is_admin: bool = False) -> dict[str, Any]:
        items = self._load_items()
        target = next((item for item in items if str(item.get("report_id") or "") == str(report_id)), None)
        if target is None or bool(target.get("deleted")):
            raise KeyError("报告不存在。")
        if not is_admin and str(target.get("user_id") or "") != str(user_id):
            raise PermissionError("无权删除该报告。")
        target["deleted"] = True
        target["deleted_at"] = now_iso()
        self._save_items(items)
        return dict(target)

    def resolve_report_path(self, report: dict[str, Any], format_name: str) -> Path | None:
        key_map = {
            "markdown": "markdown_path",
            "pdf": "pdf_path",
            "docx": "docx_path",
            "json": "json_path",
            "html": "html_path",
        }
        path_value = str(report.get(key_map.get(format_name, "")) or "").strip()
        if not path_value:
            return None
        resolved = (PROJECT_ROOT / path_value).resolve()
        if resolved.exists():
            return resolved
        suffix_map = {
            "markdown": ".md",
            "pdf": ".pdf",
            "docx": ".docx",
            "json": ".json",
            "html": ".html",
        }
        fallback = (REPORT_DIR / f"{report.get('report_id')}{suffix_map.get(format_name, '')}").resolve()
        if fallback.exists():
            return fallback
        name_hint = Path(path_value).name
        if name_hint:
            named = (REPORT_DIR / name_hint).resolve()
            if named.exists():
                return named
        return resolved

    def _load_items(self) -> list[dict[str, Any]]:
        value = read_json(self.reports_path, [])
        return value if isinstance(value, list) else []

    def _save_items(self, items: list[dict[str, Any]]) -> None:
        write_json(self.reports_path, items)
