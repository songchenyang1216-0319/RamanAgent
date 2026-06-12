"""Workspace file and context management for Agent conversations."""

from __future__ import annotations

import json
import hashlib
import mimetypes
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import UploadFile

from raman_core.methanol.config import PROJECT_ROOT

from .file_service import FileCatalogService


DEFAULT_USER_ID = "default_user"
_workspace_root_value = Path(os.getenv("WORKSPACE_ROOT") or "storage/workspaces")
WORKSPACE_ROOT = _workspace_root_value if _workspace_root_value.is_absolute() else PROJECT_ROOT / _workspace_root_value


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def safe_segment(value: str | None, fallback: str | None = None) -> str:
    text = str(value or "").strip()
    if not text:
        text = fallback or uuid4().hex
    text = Path(text).name
    text = re.sub(r"[^0-9A-Za-z\u4e00-\u9fa5._-]+", "_", text).strip("._-")
    if not text:
        text = fallback or uuid4().hex
    if text in {".", ".."}:
        text = fallback or uuid4().hex
    return text[:120]


def safe_filename(value: str | None, fallback: str = "file") -> str:
    name = Path(str(value or "")).name
    stem = safe_segment(Path(name).stem, fallback=fallback)
    suffix = Path(name).suffix.lower()
    if suffix and re.fullmatch(r"\.[0-9A-Za-z]{1,12}", suffix):
        return f"{stem}{suffix}"
    return stem


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def project_relative_or_display(path: Path) -> str:
    """Return a stable display path without assuming every workspace lives under PROJECT_ROOT."""
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(resolved)


class WorkspaceManager:
    """Create and maintain per-conversation workspace files."""

    def __init__(self, root: Path | None = None) -> None:
        from .file_processor import FileProcessorRegistry

        self.root = Path(root) if root is not None else WORKSPACE_ROOT
        self.file_catalog = FileCatalogService()
        self.file_processors = FileProcessorRegistry()

    def normalize_user_id(self, user_id: str | None = None) -> str:
        return safe_segment(user_id, fallback=DEFAULT_USER_ID)

    def normalize_conversation_id(self, conversation_id: str | None = None) -> str:
        return safe_segment(conversation_id, fallback=uuid4().hex)

    def create_workspace(self, user_id: str | None = None, conversation_id: str | None = None) -> dict[str, Any]:
        resolved_user_id = self.normalize_user_id(user_id)
        resolved_conversation_id = self.normalize_conversation_id(conversation_id)
        workspace_path = self.get_workspace_path(resolved_user_id, resolved_conversation_id)
        for child in (
            "uploads",
            "outputs",
            "logs",
            "context",
        ):
            (workspace_path / child).mkdir(parents=True, exist_ok=True)

        defaults = {
            "logs/messages.jsonl": "",
            "logs/task_steps.jsonl": "",
            "logs/skill_runs.jsonl": "",
            "logs/errors.jsonl": "",
            "context/context_summary.md": "",
        }
        for relative_path, initial_content in defaults.items():
            path = workspace_path / relative_path
            if not path.exists():
                path.write_text(initial_content, encoding="utf-8")

        json_defaults = {
            "context/active_files.json": [],
            "context/task_state.json": {
                "tasks": [],
                "current_task_id": None,
                "selected_provider": None,
                "selected_model": None,
                "updated_at": now_iso(),
            },
            "context/memory_snapshot.json": {},
        }
        for relative_path, initial_value in json_defaults.items():
            path = workspace_path / relative_path
            if not path.exists():
                write_json(path, initial_value)

        meta_path = workspace_path / "workspace_meta.json"
        meta = read_json(meta_path, {})
        if not isinstance(meta, dict):
            meta = {}
        meta.update(
            {
                "user_id": resolved_user_id,
                "conversation_id": resolved_conversation_id,
                "workspace_path": project_relative_or_display(workspace_path),
                "updated_at": now_iso(),
            }
        )
        meta.setdefault("created_at", now_iso())
        write_json(meta_path, meta)
        return {
            "user_id": resolved_user_id,
            "conversation_id": resolved_conversation_id,
            "path": workspace_path,
            "meta": meta,
        }

    def get_workspace_path(self, user_id: str | None, conversation_id: str | None) -> Path:
        user = self.normalize_user_id(user_id)
        conversation = self.normalize_conversation_id(conversation_id)
        path = (self.root / user / conversation).resolve()
        root = self.root.resolve()
        if root not in path.parents and path != root:
            raise ValueError("workspace path is outside workspace root")
        return path

    def _ensure(self, user_id: str | None, conversation_id: str | None) -> tuple[str, str, Path]:
        workspace = self.create_workspace(user_id, conversation_id)
        return workspace["user_id"], workspace["conversation_id"], workspace["path"]

    async def save_upload_file(self, user_id: str | None, conversation_id: str | None, file: UploadFile, project_id: str | None = None) -> dict[str, Any]:
        user, conversation, workspace_path = self._ensure(user_id, conversation_id)
        original_name = file.filename or "upload.bin"
        safe_name = safe_filename(original_name, fallback="upload")
        content = await file.read()
        if not content:
            raise ValueError("上传文件为空。")
        content_hash = hashlib.sha256(content).hexdigest()
        existing = self.file_catalog.find_existing_upload(
            workspace_id=conversation,
            user_id=user,
            original_filename=original_name,
            size=len(content),
            content_hash=content_hash,
        )
        if existing is not None:
            existing["processing_status"] = existing.get("processing_status") or "success"
            existing["processing_summary"] = existing.get("processing_summary") or "检测到重复上传，已复用工作区中的原文件。"
            active_files = self.read_active_files(user, conversation)
            active_files = [item for item in active_files if item.get("file_id") != existing["file_id"]]
            active_files.append(existing)
            self.update_active_files(user, conversation, active_files[-20:])
            existing["user_id"] = user
            existing["conversation_id"] = conversation
            existing["workspace_id"] = conversation
            existing["deduplicated"] = True
            existing["message"] = "检测到重复上传，已保留工作区中的原文件。"
            return existing

        target = workspace_path / "uploads" / f"{Path(safe_name).stem}_{uuid4().hex[:8]}{Path(safe_name).suffix}"
        target.write_bytes(content)
        info = self._file_info(target, workspace_path, original_name=original_name, kind="upload")
        info = self.file_catalog.register_file(
            path=target,
            original_filename=original_name,
            workspace_id=conversation,
            user_id=user,
            project_id=project_id,
            kind="upload",
        )
        processing = self.file_processors.process(
            target,
            file_id=info.get("file_id"),
            user_id=user,
            conversation_id=conversation,
        ).to_dict()
        rag_index = self._index_uploaded_file_for_rag(
            file_id=str(info.get("file_id") or ""),
            user_id=user,
            conversation_id=conversation,
            processing=processing,
        )
        processing["chunks"] = [
            {
                "chunk_id": chunk.get("chunk_id"),
                "page": chunk.get("page"),
                "section": chunk.get("section"),
                "token_estimate": chunk.get("token_estimate"),
            }
            for chunk in processing.get("chunks", [])
        ]
        info["processing"] = processing
        info["processing_status"] = "success" if processing.get("success") else "failed"
        info["processing_summary"] = processing.get("summary") or processing.get("error_message") or ""
        info["rag_index_status"] = rag_index.get("status") or ("failed" if not processing.get("success") else "pending")
        info["rag_index_error"] = rag_index.get("error_message")
        info["rag_chunk_count"] = rag_index.get("chunk_count", 0)
        info["rag_updated_at"] = now_iso()
        info["user_id"] = user
        info["conversation_id"] = conversation
        info["workspace_id"] = conversation
        info["deduplicated"] = False
        active_files = self.read_active_files(user, conversation)
        active_files = [item for item in active_files if item.get("file_id") != info["file_id"]]
        active_files.append(info)
        self.update_active_files(user, conversation, active_files[-20:])
        return info

    def _index_uploaded_file_for_rag(self, *, file_id: str, user_id: str, conversation_id: str, processing: dict[str, Any]) -> dict[str, Any]:
        if not file_id:
            return {"status": "failed", "error_message": "缺少 file_id。", "chunk_count": 0}
        if not processing.get("success"):
            return {"status": "failed", "error_message": processing.get("error_message") or "文件解析失败。", "chunk_count": 0}
        if not processing.get("chunks"):
            return {"status": "not_supported", "error_message": "该文件没有可进入文本 RAG 的内容。", "chunk_count": 0}
        try:
            from backend.services.rag import RAGService

            return RAGService().index_file(file_id, user_id, conversation_id).to_dict()
        except Exception as exc:
            return {"status": "failed", "error_message": f"RAG 索引失败：{exc}", "chunk_count": len(processing.get("chunks") or [])}

    def save_output_file(self, user_id: str | None, conversation_id: str | None, filename: str, content_or_path: Any, project_id: str | None = None) -> dict[str, Any]:
        user, conversation, workspace_path = self._ensure(user_id, conversation_id)
        safe_name = safe_filename(filename, fallback="output")
        target = workspace_path / "outputs" / f"{Path(safe_name).stem}_{uuid4().hex[:8]}{Path(safe_name).suffix}"
        source_path = None
        if isinstance(content_or_path, Path):
            source_path = content_or_path
        elif isinstance(content_or_path, str) and "\n" not in content_or_path and len(content_or_path) < 260:
            source_path = Path(content_or_path)
        if source_path is not None and source_path.exists() and source_path.is_file():
            shutil.copy2(source_path, target)
        elif isinstance(content_or_path, bytes):
            target.write_bytes(content_or_path)
        else:
            target.write_text(str(content_or_path or ""), encoding="utf-8")
        return self.file_catalog.register_file(
            path=target,
            original_filename=filename,
            workspace_id=conversation,
            user_id=user,
            project_id=project_id,
            kind="output",
        )

    def register_existing_file(
        self,
        user_id: str | None,
        conversation_id: str | None,
        path: str | Path,
        *,
        original_name: str | None = None,
        kind: str = "output",
        project_id: str | None = None,
    ) -> dict[str, Any]:
        user, conversation, _ = self._ensure(user_id, conversation_id)
        return self.file_catalog.register_file(
            path=path,
            original_filename=original_name,
            workspace_id=conversation,
            user_id=user,
            project_id=project_id,
            kind=kind,
        )

    def append_message(self, user_id: str | None, conversation_id: str | None, role: str, content: str, metadata: dict | None = None) -> dict[str, Any]:
        user, conversation, workspace_path = self._ensure(user_id, conversation_id)
        entry = {
            "message_id": uuid4().hex,
            "user_id": user,
            "conversation_id": conversation,
            "role": str(role or ""),
            "content": str(content or ""),
            "metadata": metadata or {},
            "created_at": now_iso(),
        }
        self._append_jsonl(workspace_path / "logs" / "messages.jsonl", entry)
        return entry

    def get_recent_messages(self, user_id: str | None, conversation_id: str | None, limit: int = 10) -> list[dict[str, Any]]:
        _, _, workspace_path = self._ensure(user_id, conversation_id)
        messages = self._read_jsonl(workspace_path / "logs" / "messages.jsonl")
        return messages[-max(1, int(limit)) :]

    def update_context_summary(self, user_id: str | None, conversation_id: str | None, summary: str) -> None:
        _, _, workspace_path = self._ensure(user_id, conversation_id)
        (workspace_path / "context" / "context_summary.md").write_text(str(summary or ""), encoding="utf-8")

    def read_context_summary(self, user_id: str | None, conversation_id: str | None) -> str:
        _, _, workspace_path = self._ensure(user_id, conversation_id)
        path = workspace_path / "context" / "context_summary.md"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def update_active_files(self, user_id: str | None, conversation_id: str | None, files: list[dict[str, Any]]) -> None:
        _, _, workspace_path = self._ensure(user_id, conversation_id)
        write_json(workspace_path / "context" / "active_files.json", list(files or []))

    def read_active_files(self, user_id: str | None, conversation_id: str | None) -> list[dict[str, Any]]:
        _, _, workspace_path = self._ensure(user_id, conversation_id)
        value = read_json(workspace_path / "context" / "active_files.json", [])
        return value if isinstance(value, list) else []

    def update_task_state(self, user_id: str | None, conversation_id: str | None, task_state: dict[str, Any]) -> None:
        _, _, workspace_path = self._ensure(user_id, conversation_id)
        payload = dict(task_state or {})
        payload["updated_at"] = now_iso()
        write_json(workspace_path / "context" / "task_state.json", payload)

    def read_task_state(self, user_id: str | None, conversation_id: str | None) -> dict[str, Any]:
        _, _, workspace_path = self._ensure(user_id, conversation_id)
        value = read_json(
            workspace_path / "context" / "task_state.json",
            {"tasks": [], "current_task_id": None, "selected_provider": None, "selected_model": None},
        )
        if not isinstance(value, dict):
            value = {"tasks": [], "current_task_id": None, "selected_provider": None, "selected_model": None}
        value.setdefault("selected_provider", None)
        value.setdefault("selected_model", None)
        return value

    def update_memory_snapshot(self, user_id: str | None, conversation_id: str | None, snapshot: dict[str, Any]) -> None:
        _, _, workspace_path = self._ensure(user_id, conversation_id)
        write_json(workspace_path / "context" / "memory_snapshot.json", dict(snapshot or {}))

    def append_error(self, user_id: str | None, conversation_id: str | None, error: Any) -> dict[str, Any]:
        user, conversation, workspace_path = self._ensure(user_id, conversation_id)
        entry = {
            "error_id": uuid4().hex,
            "user_id": user,
            "conversation_id": conversation,
            "error": str(error),
            "detail": error if isinstance(error, dict) else {},
            "created_at": now_iso(),
        }
        self._append_jsonl(workspace_path / "logs" / "errors.jsonl", entry)
        return entry

    def list_files(self, user_id: str | None, conversation_id: str | None) -> dict[str, list[dict[str, Any]]]:
        _, _, workspace_path = self._ensure(user_id, conversation_id)
        return {
            "uploads": [self._file_info(path, workspace_path, kind="upload") for path in sorted((workspace_path / "uploads").glob("*")) if path.is_file()],
            "outputs": [self._file_info(path, workspace_path, kind="output") for path in sorted((workspace_path / "outputs").glob("*")) if path.is_file()],
        }

    def read_workspace_context(self, user_id: str | None, conversation_id: str | None) -> dict[str, Any]:
        user, conversation, workspace_path = self._ensure(user_id, conversation_id)
        return {
            "user_id": user,
            "conversation_id": conversation,
            "workspace_path": project_relative_or_display(workspace_path),
            "context_summary": self.read_context_summary(user, conversation),
            "active_files": self.read_active_files(user, conversation),
            "task_state": self.read_task_state(user, conversation),
            "memory_snapshot": read_json(workspace_path / "context" / "memory_snapshot.json", {}),
        }

    def _file_info(self, path: Path, workspace_path: Path, original_name: str | None = None, kind: str = "") -> dict[str, Any]:
        stat = path.stat()
        relative_path = project_relative_or_display(path)
        try:
            workspace_relative_path = str(path.relative_to(workspace_path)).replace("\\", "/")
        except ValueError:
            workspace_relative_path = path.name
        return {
            "file_id": path.stem,
            "filename": path.name,
            "original_name": original_name or path.name,
            "original_filename": original_name or path.name,
            "file_type": path.suffix.lower().lstrip(".") or (mimetypes.guess_type(path.name)[0] or "application/octet-stream"),
            "path": relative_path,
            "workspace_relative_path": workspace_relative_path,
            "mime_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            "size": stat.st_size,
            "kind": kind,
            "upload_time": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            "updated_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        }

    def _append_jsonl(self, path: Path, entry: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _read_jsonl(self, path: Path) -> list[dict[str, Any]]:
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
