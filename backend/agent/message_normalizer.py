from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.agent.types import NormalizedMessage
from backend.skills.data_analysis_skill import detect_raman_table_signal, is_supported_table_suffix


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
DOCUMENT_SUFFIXES = {".txt", ".md", ".markdown", ".doc", ".docx", ".pptx", ".pdf", ".html", ".htm"}
CODE_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".html", ".css", ".sql", ".sh", ".ps1", ".json", ".yaml", ".yml"}
RAMAN_SUFFIXES = {".spc", ".spa"}


class MessageNormalizer:
    def normalize(self, payload: dict[str, Any]) -> NormalizedMessage:
        message = str(payload.get("message") or "").strip()
        files = self._normalize_files(payload)
        primary_file = files[0] if files else {}
        file_path = str(payload.get("file_path") or "").strip() or None
        if not file_path:
            file_path = str(primary_file.get("path") or primary_file.get("file_path") or "").strip() or None
        path = Path(file_path) if file_path else None
        file_suffix = (path.suffix.lower() if path else "") or None
        file_name = str(payload.get("file_name") or primary_file.get("filename") or primary_file.get("original_filename") or "").strip() or None
        if not file_name:
            file_name = path.name if path else None
        file_type = self._detect_file_type(path, file_suffix, message)
        conversation_id = str(payload.get("conversation_id") or payload.get("session_id") or "").strip()
        user_id = str(payload.get("user_id") or "default_user").strip() or "default_user"
        model_id = str(payload.get("model_id") or "").strip() or None
        provider_id = str(payload.get("provider_id") or "").strip() or None
        enabled_skills = [str(item).strip() for item in (payload.get("enabled_skills") or []) if str(item).strip()]
        metadata = dict(payload.get("metadata") or {})
        file_ids = self._normalize_string_list(payload.get("file_ids") or [item.get("file_id") for item in files])
        knowledge_base_ids = self._normalize_string_list(payload.get("knowledge_base_ids"))
        rag_scope = str(payload.get("rag_scope") or metadata.get("rag_scope") or "").strip() or None
        selected_model = {
            "provider_id": provider_id,
            "model_id": model_id,
        }
        return NormalizedMessage(
            message=message or ("请分析这个文件" if file_path else ""),
            raw_message=str(payload.get("message") or ""),
            conversation_id=conversation_id,
            session_id=conversation_id,
            user_id=user_id,
            debug=bool(payload.get("debug", False)),
            provider_id=provider_id,
            model_id=model_id,
            selected_model=selected_model,
            enabled_skills=enabled_skills,
            workspace_id=str(payload.get("workspace_id") or conversation_id or "").strip() or None,
            metadata=metadata,
            file_path=file_path,
            file_name=file_name,
            file_suffix=file_suffix,
            file_type=file_type,
            has_file=bool(file_path or files or file_ids),
            files=files,
            file_ids=file_ids,
            selected_files=files,
            knowledge_base_ids=knowledge_base_ids,
            rag_scope=rag_scope,
        )

    def _normalize_string_list(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            raw_items = value.split(",")
        elif isinstance(value, (list, tuple, set)):
            raw_items = list(value)
        else:
            raw_items = [value]
        result = []
        seen = set()
        for item in raw_items:
            text = str(item or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
        return result

    def _normalize_files(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        raw_files = payload.get("files") or payload.get("attachments") or []
        if isinstance(raw_files, dict):
            raw_files = [raw_files]
        if not isinstance(raw_files, list):
            raw_files = []
        result: list[dict[str, Any]] = []
        seen = set()
        for item in raw_files:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or item.get("file_path") or "").strip()
            file_id = str(item.get("file_id") or "").strip()
            key = file_id or path
            if not key or key in seen:
                continue
            seen.add(key)
            result.append(dict(item))
        if not result and payload.get("file_path"):
            result.append(
                {
                    "file_id": payload.get("file_id"),
                    "filename": payload.get("file_name") or Path(str(payload.get("file_path"))).name,
                    "path": payload.get("file_path"),
                    "file_type": payload.get("file_type"),
                }
            )
        return result

    def _detect_file_type(self, path: Path | None, suffix: str | None, message: str) -> str | None:
        suffix = str(suffix or "").lower()
        if not path or not suffix:
            return None
        if suffix in IMAGE_SUFFIXES:
            return "image"
        if suffix in CODE_SUFFIXES:
            return "code"
        if suffix in DOCUMENT_SUFFIXES:
            return "document"
        if suffix in RAMAN_SUFFIXES:
            return "raman"
        if is_supported_table_suffix(suffix):
            if any(keyword in str(message or "").lower() for keyword in ("raman", "sers", "光谱", "峰位", "甲醇")):
                return "raman"
            signal = detect_raman_table_signal(path)
            return "raman" if signal.get("is_raman") else "table"
        return "file"
