from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.agent.types import NormalizedMessage
from backend.skills.data_analysis_skill import detect_raman_table_signal, is_supported_table_suffix
from raman_core.methanol.config import PROJECT_ROOT


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
DOCUMENT_SUFFIXES = {".txt", ".md", ".markdown", ".doc", ".docx", ".pptx", ".pdf", ".html", ".htm"}
CODE_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".html", ".css", ".sql", ".sh", ".ps1", ".json", ".yaml", ".yml"}
RAMAN_SUFFIXES = {".spc", ".spa"}


class MessageNormalizer:
    def normalize(self, payload: dict[str, Any]) -> NormalizedMessage:
        message = str(payload.get("message") or "").strip()
        conversation_id = str(payload.get("conversation_id") or payload.get("session_id") or "").strip()
        user_id = str(payload.get("user_id") or "default_user").strip() or "default_user"
        files = self._normalize_files(payload)
        primary_file = files[0] if files else {}
        file_path = str(payload.get("file_path") or "").strip() or None
        if not file_path:
            file_path = str(primary_file.get("path") or primary_file.get("file_path") or "").strip() or None
        if not file_path and self._message_mentions_file_context(message):
            active_file = self._resolve_active_file(user_id, conversation_id, message)
            if active_file:
                files = [active_file, *files]
                primary_file = active_file
                file_path = str(active_file.get("path") or active_file.get("file_path") or "").strip() or None
        path = Path(file_path) if file_path else None
        file_suffix = (path.suffix.lower() if path else "") or None
        file_name = str(payload.get("file_name") or primary_file.get("filename") or primary_file.get("original_filename") or "").strip() or None
        if not file_name:
            file_name = path.name if path else None
        file_type = self._detect_file_type(path, file_suffix, message)
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

    def _message_mentions_file_context(self, message: str) -> bool:
        text = str(message or "").lower()
        markers = (
            "刚才",
            "上次",
            "它",
            "他",
            "其",
            "这个文件",
            "那个文件",
            "当前文件",
            "上一个文件",
            "上传的文件",
            "这个表格",
            "那个表格",
            "这个文档",
            "那个文档",
            "这个图片",
            "那张图",
            "这张图",
            "这个代码",
            "这个脚本",
            "这个csv",
            "这个 csv",
            "那个csv",
            "那个 csv",
            "csv文件",
            "csv 文件",
            "excel文件",
            "excel 文件",
            "主要内容",
            "内容是什么",
            "内容总结",
            "总结一下",
            "总结这个",
            "分析这个",
            "处理这个",
            "转换这个",
            "导出这个",
            "this file",
            "uploaded file",
            "previous file",
        )
        return any(marker in text for marker in markers)

    def _resolve_active_file(self, user_id: str, conversation_id: str, message: str) -> dict[str, Any] | None:
        if not conversation_id:
            return None
        try:
            from backend.services.workspace_manager import WorkspaceManager

            active_files = WorkspaceManager().read_active_files(user_id, conversation_id)
        except Exception:
            return None
        if not active_files:
            return None

        suffix_preferences = self._suffix_preferences(message)
        ordered_files = list(reversed(active_files))
        if suffix_preferences:
            preferred = []
            rest = []
            for item in ordered_files:
                suffix = Path(str(item.get("filename") or item.get("original_filename") or item.get("path") or "")).suffix.lower()
                if suffix in suffix_preferences:
                    preferred.append(item)
                else:
                    rest.append(item)
            ordered_files = preferred + rest

        for item in ordered_files:
            raw_path = str(item.get("path") or item.get("file_path") or "").strip()
            if not raw_path:
                continue
            path = Path(raw_path)
            if not path.is_absolute():
                path = PROJECT_ROOT / path
            if path.exists() and path.is_file():
                resolved = dict(item)
                resolved["path"] = str(path)
                resolved.setdefault("filename", path.name)
                return resolved
        return None

    def _suffix_preferences(self, message: str) -> list[str]:
        text = str(message or "").lower()
        preferences: list[str] = []
        if any(marker in text for marker in ("csv", "表格", "excel", "xlsx", "xls")):
            preferences.extend([".csv", ".xlsx", ".xls"])
        if any(marker in text for marker in ("文档", "报告", "doc", "pdf", "word", "论文")):
            preferences.extend([".docx", ".doc", ".pdf", ".txt", ".md", ".markdown"])
        if any(marker in text for marker in ("图片", "图像", "截图", "这张图", "那张图", "ocr")):
            preferences.extend([".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"])
        if any(marker in text for marker in ("代码", "脚本", "函数", "bug", "报错")):
            preferences.extend([".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".html", ".css", ".sql", ".sh", ".ps1", ".json", ".yaml", ".yml"])
        deduped = []
        for suffix in preferences:
            if suffix not in deduped:
                deduped.append(suffix)
        return deduped

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
