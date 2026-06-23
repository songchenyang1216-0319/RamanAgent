from __future__ import annotations

from pathlib import Path
from typing import Callable

from fastapi import HTTPException

from backend.agent.chat_context import ChatExecutionContext
from backend.agent.chat_request_parser import ParsedChatRequest


class ChatContextBuilder:
    def __init__(
        self,
        *,
        workspace_manager,
        file_catalog,
        user_memory_manager,
        ensure_session_id: Callable[[str | None], str],
        update_session: Callable[[str, str, object], None],
        get_session: Callable[[str], dict | None],
        project_root: Path,
    ) -> None:
        self.workspace_manager = workspace_manager
        self.file_catalog = file_catalog
        self.user_memory_manager = user_memory_manager
        self.ensure_session_id = ensure_session_id
        self.update_session = update_session
        self.get_session = get_session
        self.project_root = Path(project_root)

    async def build(self, parsed_request: ParsedChatRequest) -> ChatExecutionContext:
        conversation_id = str(parsed_request.conversation_id).strip() if parsed_request.conversation_id else None
        resolved_session_id = self.ensure_session_id(conversation_id)
        workspace = self.workspace_manager.create_workspace(parsed_request.user_id, resolved_session_id)
        resolved_user_id = str(workspace["user_id"])
        self.update_session(resolved_session_id, "user_id", resolved_user_id)

        effective_message = parsed_request.message or "请分析这个文件"
        memory_note = self._extract_memory_note(effective_message)
        if memory_note:
            self.user_memory_manager.remember_note(resolved_user_id, memory_note)
        user_memory = self.user_memory_manager.get_user_memory(resolved_user_id)
        self.workspace_manager.update_memory_snapshot(resolved_user_id, resolved_session_id, user_memory)
        workspace_context = self.workspace_manager.read_workspace_context(resolved_user_id, resolved_session_id)

        file_ids = self._dedupe_preserve_order(parsed_request.file_ids)
        knowledge_base_ids = self._dedupe_preserve_order(parsed_request.knowledge_base_ids)
        selected_files = await self._resolve_selected_files(
            parsed_request=parsed_request,
            user_id=resolved_user_id,
            conversation_id=resolved_session_id,
            effective_message=effective_message,
            file_ids=file_ids,
        )

        orchestrator_payload: dict[str, object] = {
            "message": effective_message,
            "conversation_id": resolved_session_id,
            "session_id": resolved_session_id,
            "user_id": resolved_user_id,
            "provider_id": parsed_request.provider_id,
            "model_id": parsed_request.model_id,
            "debug": parsed_request.debug,
            "metadata": dict(parsed_request.metadata or {}),
            "explicit_has_file": bool(parsed_request.uploaded_files or file_ids),
            "file_ids": list(file_ids),
            "knowledge_base_ids": list(knowledge_base_ids),
            "rag_scope": parsed_request.rag_scope,
        }
        self._attach_selected_files(orchestrator_payload, selected_files)
        if not selected_files:
            self._attach_last_file_if_referenced(orchestrator_payload, resolved_session_id, effective_message)

        return ChatExecutionContext(
            message=parsed_request.message,
            effective_message=effective_message,
            user_id=resolved_user_id,
            conversation_id=resolved_session_id,
            session_id=resolved_session_id,
            provider_id=parsed_request.provider_id,
            model_id=parsed_request.model_id,
            debug=parsed_request.debug,
            metadata=dict(parsed_request.metadata or {}),
            rag_scope=parsed_request.rag_scope,
            file_ids=list(orchestrator_payload.get("file_ids") or file_ids),
            knowledge_base_ids=knowledge_base_ids,
            uploaded_files=list(parsed_request.uploaded_files or []),
            selected_files=selected_files,
            orchestrator_payload=orchestrator_payload,
            workspace_context=workspace_context,
            user_memory=user_memory,
            request_content_type=parsed_request.request_content_type,
        )

    async def _resolve_selected_files(
        self,
        *,
        parsed_request: ParsedChatRequest,
        user_id: str,
        conversation_id: str,
        effective_message: str,
        file_ids: list[str],
    ) -> list[dict]:
        if parsed_request.uploaded_files:
            selected_files = []
            for item in parsed_request.uploaded_files:
                try:
                    info = await self.workspace_manager.save_upload_file(user_id, conversation_id, item)
                except ValueError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
                selected_files.append(info)
            return selected_files

        if file_ids:
            selected_files = self.file_catalog.get_files_by_ids(file_ids, user_id=user_id, is_admin=False)
            if len(selected_files) != len(file_ids):
                found = {str(item.get("file_id") or "") for item in selected_files}
                missing = [file_id for file_id in file_ids if file_id not in found]
                raise HTTPException(status_code=404, detail={"message": "部分文件不存在或无权访问。", "file_ids": missing})
            return selected_files

        if self._message_mentions_multi_file_context(effective_message):
            active_files = self.workspace_manager.read_active_files(user_id, conversation_id)[-5:]
            if active_files:
                return list(active_files)

        referenced_active_file = self._resolve_referenced_active_file(user_id, conversation_id, effective_message)
        if referenced_active_file is not None:
            _save_path, active_item = referenced_active_file
            return [active_item]

        return []

    def _attach_selected_files(self, payload: dict[str, object], selected_files: list[dict]) -> None:
        if not selected_files:
            return
        payload["files"] = selected_files
        payload["file_ids"] = [str(item.get("file_id")) for item in selected_files if item.get("file_id")]
        first_path = self.project_root / str(selected_files[0].get("path") or "")
        payload["file_path"] = str(first_path)
        payload["file_name"] = str(selected_files[0].get("filename") or first_path.name)

    def _attach_last_file_if_referenced(self, payload: dict[str, object], session_id: str, effective_message: str) -> None:
        session = self.get_session(session_id) or {}
        last_file = str(session.get("last_file") or "").strip()
        if not last_file or not self._message_mentions_file_context(effective_message):
            return
        candidate = Path(last_file)
        if not candidate.is_absolute():
            candidate = self.project_root / candidate
        try:
            resolved_candidate = candidate.resolve()
        except Exception:
            resolved_candidate = candidate
        if resolved_candidate.exists() and resolved_candidate.is_file():
            payload["file_path"] = str(resolved_candidate)
            payload["file_name"] = resolved_candidate.name

    def _resolve_referenced_active_file(self, user_id: str, conversation_id: str, message: str) -> tuple[Path, dict] | None:
        text = str(message or "")
        if not self._message_mentions_file_context(text):
            return None
        active_files = self.workspace_manager.read_active_files(user_id, conversation_id)
        if not active_files:
            return None

        lowered = text.lower()
        suffix_preferences: list[str] = []
        if "csv" in lowered or "表格" in text:
            suffix_preferences.extend([".csv", ".xlsx", ".xls"])
        if "excel" in lowered or "xlsx" in lowered or "xls" in lowered:
            suffix_preferences.extend([".xlsx", ".xls", ".csv"])
        if any(marker in text for marker in ("文档", "报告", "doc", "pdf", "word")):
            suffix_preferences.extend([".docx", ".doc", ".pdf", ".txt", ".md"])

        ordered_files = list(reversed(active_files))
        if suffix_preferences:
            preferred = []
            rest = []
            for item in ordered_files:
                name = str(item.get("filename") or item.get("original_filename") or item.get("path") or "")
                suffix = Path(name).suffix.lower()
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
                path = self.project_root / path
            try:
                resolved = path.resolve()
            except Exception:
                continue
            if resolved.exists() and resolved.is_file():
                return resolved, item
        return None

    @staticmethod
    def _message_mentions_file_context(message: str) -> bool:
        text = str(message or "").lower()
        markers = (
            "刚才",
            "上次",
            "它",
            "他",
            "其",
            "那个文件",
            "那个csv",
            "那个 csv",
            "那个表格",
            "这个文件",
            "这个csv",
            "这个 csv",
            "这个表格",
            "当前文件",
            "上一个文件",
            "csv文件",
            "csv 文件",
            "excel文件",
            "excel 文件",
            "主要内容",
            "内容是什么",
            "内容总结",
            "继续处理",
            "继续分析",
            "总结这个",
            "总结一下",
            "分析这个",
            "处理这个",
            "转换这个",
            "生成报告",
            "this file",
            "uploaded file",
            "previous file",
        )
        stripped = str(message or "").strip()
        if stripped.startswith("按") or any(marker in stripped for marker in ("分组", "每个城市", "每个省", "各城市", "各省", "按城市", "按省份")):
            return True
        return any(marker in text for marker in markers)

    @staticmethod
    def _message_mentions_multi_file_context(message: str) -> bool:
        return any(
            marker in str(message or "")
            for marker in ("这些文件", "这些文档", "这几个文件", "所有文件", "全部文件", "刚才这些", "刚才那些")
        )

    @staticmethod
    def _extract_memory_note(message: str) -> str | None:
        text = str(message or "").strip()
        for marker in ("请记住", "帮我记住", "记住"):
            if text.startswith(marker):
                note = text[len(marker) :].strip(" ：:，,。")
                return note or None
        return None

    @staticmethod
    def _dedupe_preserve_order(values: list[str]) -> list[str]:
        result = []
        seen = set()
        for value in values or []:
            text = str(value or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
        return result
