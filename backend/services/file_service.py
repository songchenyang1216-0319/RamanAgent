"""文件中心索引服务。"""

from __future__ import annotations

import json
import hashlib
import mimetypes
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from raman_core.methanol.config import PROJECT_ROOT


FILE_INDEX_PATH = PROJECT_ROOT / "storage" / "file_index.json"
TEXT_FILE_SUFFIXES = {".txt", ".md", ".markdown", ".json", ".csv", ".tsv", ".log", ".html", ".htm", ".yaml", ".yml"}
IMAGE_FILE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


class FileCatalogService:
    """用 JSON 文件维护项目文件中心索引。"""

    def __init__(self, index_path: Path | None = None) -> None:
        self.index_path = Path(index_path) if index_path is not None else FILE_INDEX_PATH

    def list_files(
        self,
        *,
        user_id: str | None = None,
        workspace_id: str | None = None,
        project_id: str | None = None,
        include_missing: bool = False,
    ) -> list[dict[str, Any]]:
        items = []
        for item in self._load_items():
            if user_id and str(item.get("user_id") or "") != str(user_id):
                continue
            if workspace_id and str(item.get("workspace_id") or "") != str(workspace_id):
                continue
            if project_id is not None and item.get("project_id") != project_id:
                continue
            if not include_missing and not self._exists(item):
                continue
            items.append(self._enrich_item(item))
        items.sort(key=lambda value: str(value.get("upload_time") or ""), reverse=True)
        return items

    def find_existing_upload(
        self,
        *,
        workspace_id: str,
        user_id: str,
        original_filename: str,
        size: int,
        content_hash: str,
    ) -> dict[str, Any] | None:
        normalized_name = str(original_filename or "").strip()
        for item in self._load_items():
            if str(item.get("workspace_id") or "") != str(workspace_id):
                continue
            if str(item.get("user_id") or "") != str(user_id):
                continue
            if str(item.get("kind") or "") != "upload":
                continue
            if str(item.get("original_filename") or "").strip() != normalized_name:
                continue
            if int(item.get("size") or 0) != int(size):
                continue
            item_hash = str(item.get("content_hash") or "").strip()
            if not item_hash:
                path = self._resolve_item_path(item)
                if not path.exists() or not path.is_file():
                    continue
                item_hash = self._compute_content_hash(path)
                item["content_hash"] = item_hash
            if item_hash == content_hash:
                self._save_items(self._load_items_with_updates({str(item.get("file_id") or ""): item}))
                return self._enrich_item(item)
        return None

    def cleanup_workspace_duplicates(
        self,
        *,
        workspace_id: str,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        items = self._load_items()
        changed = False
        grouped: dict[tuple[str, str, str, int, str], list[dict[str, Any]]] = {}
        retained_updates: dict[str, dict[str, Any]] = {}
        removed: list[dict[str, Any]] = []
        scoped_file_ids: set[str] = set()

        for item in items:
            file_id = str(item.get("file_id") or "")
            if str(item.get("workspace_id") or "") != str(workspace_id):
                continue
            if user_id is not None and str(item.get("user_id") or "") != str(user_id):
                continue
            if str(item.get("kind") or "") != "upload":
                continue
            scoped_file_ids.add(file_id)
            path = self._resolve_item_path(item)
            if not path.exists() or not path.is_file():
                continue
            content_hash = str(item.get("content_hash") or "").strip()
            if not content_hash:
                content_hash = self._compute_content_hash(path)
                item["content_hash"] = content_hash
                retained_updates[file_id] = item
                changed = True
            key = (
                str(item.get("user_id") or ""),
                str(item.get("workspace_id") or ""),
                str(item.get("original_filename") or ""),
                int(item.get("size") or 0),
                content_hash,
            )
            grouped.setdefault(key, []).append(item)

        duplicate_map: dict[str, str] = {}
        survivor_ids: set[str] = set()
        for group in grouped.values():
            if len(group) == 1:
                only = group[0]
                survivor_ids.add(str(only.get("file_id") or ""))
                continue
            ordered = sorted(
                group,
                key=lambda value: (
                    str(value.get("upload_time") or ""),
                    str(value.get("updated_at") or ""),
                    str(value.get("file_id") or ""),
                ),
            )
            keeper = ordered[0]
            keeper_id = str(keeper.get("file_id") or "")
            survivor_ids.add(keeper_id)
            for duplicate in ordered[1:]:
                duplicate_id = str(duplicate.get("file_id") or "")
                duplicate_map[duplicate_id] = keeper_id
                removed.append(self._enrich_item(duplicate))
                changed = True
                path = self._resolve_item_path(duplicate)
                if path.exists() and path.is_file():
                    path.unlink()

        survivors: list[dict[str, Any]] = []
        for item in items:
            file_id = str(item.get("file_id") or "")
            if file_id in duplicate_map:
                continue
            if file_id in scoped_file_ids:
                survivors.append(retained_updates.get(file_id, item))
                continue
            survivors.append(item)

        if changed:
            self._save_items(survivors)
        return {
            "kept_file_ids": sorted(survivor_ids),
            "removed_files": removed,
            "replaced_by": duplicate_map,
            "changed": changed,
        }

    def get_file(self, file_id: str) -> dict[str, Any] | None:
        for item in self._load_items():
            if str(item.get("file_id") or "") == str(file_id):
                return self._enrich_item(item)
        return None

    def get_file_for_user(self, file_id: str, *, user_id: str, is_admin: bool = False) -> dict[str, Any] | None:
        item = self.get_file(file_id)
        if item is None:
            return None
        if is_admin:
            return item
        if str(item.get("user_id") or "") != str(user_id):
            return None
        return item

    def register_file(
        self,
        *,
        path: str | Path,
        original_filename: str | None,
        workspace_id: str,
        user_id: str,
        project_id: str | None = None,
        kind: str = "upload",
    ) -> dict[str, Any]:
        file_path = Path(path)
        if not file_path.exists() or not file_path.is_file():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        relative_path = self._relative_path(file_path)
        items = self._load_items()
        existing = next((item for item in items if item.get("path") == relative_path), None)
        payload = self._build_file_payload(
            file_path=file_path,
            original_filename=original_filename,
            workspace_id=workspace_id,
            user_id=user_id,
            project_id=project_id,
            kind=kind,
            existing=existing,
        )
        if existing is None:
            items.append(payload)
        else:
            existing_index = items.index(existing)
            items[existing_index] = payload
        self._save_items(items)
        return self._enrich_item(payload)

    def delete_file(self, file_id: str) -> dict[str, Any]:
        items = self._load_items()
        target = next((item for item in items if str(item.get("file_id") or "") == str(file_id)), None)
        if target is None:
            raise KeyError(f"未找到文件: {file_id}")

        path = self._resolve_item_path(target)
        if path.exists() and path.is_file():
            path.unlink()
        items = [item for item in items if str(item.get("file_id") or "") != str(file_id)]
        self._save_items(items)
        return self._enrich_item(target)

    def update_file_project(self, file_id: str, project_id: str | None, *, user_id: str | None = None, is_admin: bool = False) -> dict[str, Any]:
        items = self._load_items()
        target = next((item for item in items if str(item.get("file_id") or "") == str(file_id)), None)
        if target is None:
            raise KeyError(f"未找到文件: {file_id}")
        if not is_admin and user_id and str(target.get("user_id") or "") != str(user_id):
            raise PermissionError("无权修改该文件。")
        target["project_id"] = project_id
        target["updated_at"] = datetime.now().isoformat(timespec="seconds")
        self._save_items(items)
        return self._enrich_item(target)

    def get_files_by_ids(self, file_ids: list[str], *, user_id: str, is_admin: bool = False) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for file_id in file_ids:
            item = self.get_file_for_user(file_id, user_id=user_id, is_admin=is_admin)
            if item is not None:
                result.append(item)
        return result

    def build_download_name(self, file_item: dict[str, Any]) -> str:
        return str(file_item.get("original_filename") or file_item.get("filename") or file_item.get("file_id") or "download.bin")

    def preview_file(self, file_id: str, max_lines: int = 20, max_chars: int = 4000) -> dict[str, Any]:
        item = self.get_file(file_id)
        if item is None:
            raise KeyError(f"未找到文件: {file_id}")

        path = self._resolve_item_path(item)
        suffix = path.suffix.lower()
        preview_type = "binary"
        preview_payload: dict[str, Any] = {
            "success": True,
            "file_id": item["file_id"],
            "filename": item["filename"],
            "original_filename": item.get("original_filename"),
            "file_type": item.get("file_type"),
            "size": item.get("size"),
            "preview_type": preview_type,
            "preview_url": f"/api/files/{item['file_id']}/download",
            "content": "",
            "lines": [],
        }

        if suffix in IMAGE_FILE_SUFFIXES:
            preview_payload["preview_type"] = "image"
            return preview_payload

        if suffix == ".pdf":
            preview_payload["preview_type"] = "pdf"
            return preview_payload

        if suffix in TEXT_FILE_SUFFIXES or str(item.get("mime_type") or "").startswith("text/"):
            text = path.read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines()
            clipped = "\n".join(lines[:max_lines])[:max_chars]
            preview_payload["preview_type"] = "text"
            preview_payload["content"] = clipped
            preview_payload["lines"] = lines[:max_lines]
            preview_payload["truncated"] = len(lines) > max_lines or len(text) > len(clipped)
            if suffix == ".csv":
                preview_payload["preview_type"] = "csv"
            if suffix in {".html", ".htm"}:
                preview_payload["preview_type"] = "html"
            return preview_payload

        preview_payload["message"] = "当前文件类型暂不支持文本预览，请直接下载查看。"
        return preview_payload

    def _load_items(self) -> list[dict[str, Any]]:
        value = _read_json(self.index_path, [])
        return value if isinstance(value, list) else []

    def _save_items(self, items: list[dict[str, Any]]) -> None:
        _write_json(self.index_path, items)

    def _load_items_with_updates(self, updates: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        items = self._load_items()
        if not updates:
            return items
        return [updates.get(str(item.get("file_id") or ""), item) for item in items]

    def _relative_path(self, path: Path) -> str:
        resolved = path.resolve()
        project_root = PROJECT_ROOT.resolve()
        if resolved != project_root and project_root not in resolved.parents:
            raise ValueError("文件路径超出项目目录。")
        return str(resolved.relative_to(project_root)).replace("\\", "/")

    def _resolve_item_path(self, item: dict[str, Any]) -> Path:
        return (PROJECT_ROOT / str(item.get("path") or "")).resolve()

    def _exists(self, item: dict[str, Any]) -> bool:
        try:
            return self._resolve_item_path(item).exists()
        except Exception:
            return False

    def _compute_content_hash(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _build_file_payload(
        self,
        *,
        file_path: Path,
        original_filename: str | None,
        workspace_id: str,
        user_id: str,
        project_id: str | None,
        kind: str,
        existing: dict[str, Any] | None,
    ) -> dict[str, Any]:
        stat = file_path.stat()
        mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        suffix = file_path.suffix.lower().lstrip(".")
        created = datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
        return {
            "file_id": str((existing or {}).get("file_id") or uuid4().hex[:12]),
            "filename": file_path.name,
            "original_filename": original_filename or file_path.name,
            "file_type": suffix or mime_type,
            "mime_type": mime_type,
            "size": stat.st_size,
            "upload_time": str((existing or {}).get("upload_time") or created),
            "updated_at": created,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "user_id": user_id,
            "path": self._relative_path(file_path),
            "kind": kind,
            "content_hash": str((existing or {}).get("content_hash") or self._compute_content_hash(file_path)),
        }

    def _enrich_item(self, item: dict[str, Any]) -> dict[str, Any]:
        payload = dict(item)
        payload["original_name"] = payload.get("original_filename")
        payload["download_url"] = f"/api/files/{payload['file_id']}/download"
        payload["preview_url"] = f"/api/files/{payload['file_id']}/preview"
        return payload
