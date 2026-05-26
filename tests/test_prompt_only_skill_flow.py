from __future__ import annotations

import io
import json
import sys
import tempfile
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.main import app
import backend.skills.registry as registry
import backend.skills.upload_service as upload_service
from backend.services.llm_service import LLMService
from backend.skills.uploaded_package_skill import discover_uploaded_package_skills


def _make_zip_bytes(structure: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path, content in structure.items():
            zf.writestr(path, content)
    return buffer.getvalue()


def _make_minimal_docx_bytes(text: str) -> bytes:
    document_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>{text}</w:t></w:r></w:p>
  </w:body>
</w:document>
"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<?xml version=\"1.0\" encoding=\"UTF-8\"?><Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\"></Types>")
        zf.writestr("_rels/.rels", "<?xml version=\"1.0\" encoding=\"UTF-8\"?><Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\"></Relationships>")
        zf.writestr("word/document.xml", document_xml)
    return buffer.getvalue()


def test_prompt_only_skill_upload_and_chat_flow() -> None:
    original_upload_dir = upload_service.SKILL_UPLOAD_DIR
    original_extract_dir = upload_service.SKILL_EXTRACT_DIR
    original_meta_path = upload_service.SKILL_UPLOAD_META_PATH
    original_custom_root = registry.CUSTOM_SKILL_ROOT
    original_llm_method = LLMService.generate_skill_augmented_reply

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        temp_upload_dir = temp_root / "skill_uploads"
        temp_extract_dir = temp_root / "custom"
        temp_meta_path = temp_root / "uploaded_skills.json"
        temp_upload_dir.mkdir(parents=True, exist_ok=True)
        temp_extract_dir.mkdir(parents=True, exist_ok=True)

        try:
            upload_service.SKILL_UPLOAD_DIR = temp_upload_dir
            upload_service.SKILL_EXTRACT_DIR = temp_extract_dir
            upload_service.SKILL_UPLOAD_META_PATH = temp_meta_path

            prompt_only_zip = _make_zip_bytes(
                {
                    "SKILL.md": """---
name: text-document-processor
description: Use this skill when the user asks to process text documents.
---

# Text Document Processor Skill

请优先处理翻译、总结、对照、提炼、整理成 Markdown 等文本任务。
""",
                    "README.md": "# README\n\n这是提示词型 Skill 的说明文件。",
                    "references/translation_rules.md": "# Translation Rules\n\n1. 保留原意。\n2. 使用自然中文。",
                    "assets/bilingual_template.md": "# Template\n\n## Original\n\n## Translation\n",
                }
            )

            upload_result = upload_service.save_uploaded_skill("text-document-processor.zip", prompt_only_zip)
            assert upload_result["success"] is True
            assert upload_result["skill_mode"] == "prompt_only"
            assert "提示词型 Skill 已安装" in upload_result["message"]

            discovered = discover_uploaded_package_skills(temp_extract_dir)
            assert len(discovered) == 1
            assert discovered[0].skill_mode == "prompt_only"

            registry.CUSTOM_SKILL_ROOT = temp_extract_dir

            def _fake_generate_skill_augmented_reply(self, *, skill_context: str, user_message: str, conversation_context: dict | None = None) -> dict:
                return {
                    "success": True,
                    "reply": f"已按提示词型 Skill 回答：{user_message}",
                    "error_message": None,
                    "raw_response": {"skill_context_preview": skill_context[:120]},
                    "warnings": [],
                }

            LLMService.generate_skill_augmented_reply = _fake_generate_skill_augmented_reply

            client = TestClient(app)
            response = client.post(
                "/api/agent/chat",
                json={"message": "把这段英文翻译成中文。", "debug": True},
            )
            payload = response.json()
            assert response.status_code == 200
            assert payload["success"] is True
            assert payload["skill_name"] == "text-document-processor"
            assert payload["error_message"] is None
            assert (payload.get("skill_mode") or payload["messages"][0].get("skill_mode")) == "prompt_only"
            assert "已按提示词型 Skill 回答" in payload["reply"]
        finally:
            upload_service.SKILL_UPLOAD_DIR = original_upload_dir
            upload_service.SKILL_EXTRACT_DIR = original_extract_dir
            upload_service.SKILL_UPLOAD_META_PATH = original_meta_path
            registry.CUSTOM_SKILL_ROOT = original_custom_root
            LLMService.generate_skill_augmented_reply = original_llm_method


def test_invalid_skill_upload_rejects_readme_only_package() -> None:
    original_upload_dir = upload_service.SKILL_UPLOAD_DIR
    original_extract_dir = upload_service.SKILL_EXTRACT_DIR
    original_meta_path = upload_service.SKILL_UPLOAD_META_PATH

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        temp_upload_dir = temp_root / "skill_uploads"
        temp_extract_dir = temp_root / "custom"
        temp_meta_path = temp_root / "uploaded_skills.json"
        temp_upload_dir.mkdir(parents=True, exist_ok=True)
        temp_extract_dir.mkdir(parents=True, exist_ok=True)

        try:
            upload_service.SKILL_UPLOAD_DIR = temp_upload_dir
            upload_service.SKILL_EXTRACT_DIR = temp_extract_dir
            upload_service.SKILL_UPLOAD_META_PATH = temp_meta_path

            bad_zip = _make_zip_bytes(
                {
                    "README.md": "# README only\n\n没有 SKILL.md 或 manifest.json。",
                }
            )

            try:
                upload_service.save_uploaded_skill("bad-skill.zip", bad_zip)
                raise AssertionError("expected ValueError for invalid skill package")
            except ValueError as exc:
                assert "SKILL.md" in str(exc) or "manifest.json" in str(exc)
        finally:
            upload_service.SKILL_UPLOAD_DIR = original_upload_dir
            upload_service.SKILL_EXTRACT_DIR = original_extract_dir
            upload_service.SKILL_UPLOAD_META_PATH = original_meta_path


def test_delete_uploaded_skill_accepts_discovered_runtime_name_for_legacy_record() -> None:
    original_upload_dir = upload_service.SKILL_UPLOAD_DIR
    original_extract_dir = upload_service.SKILL_EXTRACT_DIR
    original_meta_path = upload_service.SKILL_UPLOAD_META_PATH

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        temp_upload_dir = temp_root / "skill_uploads"
        temp_extract_dir = temp_root / "custom"
        temp_meta_path = temp_root / "uploaded_skills.json"
        temp_upload_dir.mkdir(parents=True, exist_ok=True)
        temp_extract_dir.mkdir(parents=True, exist_ok=True)

        try:
            upload_service.SKILL_UPLOAD_DIR = temp_upload_dir
            upload_service.SKILL_EXTRACT_DIR = temp_extract_dir
            upload_service.SKILL_UPLOAD_META_PATH = temp_meta_path

            archive_path = temp_upload_dir / "agent_skill_upload_test_v1_20260522_172759.zip"
            archive_path.write_bytes(b"legacy zip payload")

            extract_dir = temp_extract_dir / "agent_skill_upload_test_v1"
            package_dir = extract_dir / "agent_skill_upload_test_v1"
            package_dir.mkdir(parents=True, exist_ok=True)
            (package_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "name": "agent-skill-upload-test",
                        "display_name": "Agent Skill Upload Test",
                        "version": "1.0.0",
                        "description": "A safe diagnostic Skill package for testing whether an Agent can discover, enable, and use an uploaded Skill.",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (package_dir / "SKILL.md").write_text("# Agent Skill Upload Test", encoding="utf-8")

            upload_service._write_upload_meta(
                [
                    {
                        "name": "agent_skill_upload_test_v1",
                        "display_name": "agent_skill_upload_test_v1",
                        "description": "用户上传的 Skill 压缩包，已保存并解压，等待后续加载。",
                        "upload_status": "pending_load",
                        "uploaded_at": "2026-05-22T17:27:59",
                        "archive_path": upload_service._record_path_value(archive_path),
                        "extract_dir": upload_service._record_path_value(extract_dir),
                        "reload_required": True,
                        "unavailable_reason": "当前实现已完成保存与解压，需刷新 Skills 列表；若未接入自动注册，则重启后再加载。",
                        "usage": "上传成功后会在 Skills 列表中显示为 source: uploaded / 待加载。",
                        "source": "uploaded",
                    }
                ]
            )

            result = upload_service.delete_uploaded_skill("agent-skill-upload-test")
            assert result["success"] is True
            assert not archive_path.exists()
            assert not extract_dir.exists()
            assert json.loads(temp_meta_path.read_text(encoding="utf-8")) == []
        finally:
            upload_service.SKILL_UPLOAD_DIR = original_upload_dir
            upload_service.SKILL_EXTRACT_DIR = original_extract_dir
            upload_service.SKILL_UPLOAD_META_PATH = original_meta_path


def test_prompt_only_skill_wins_docx_route_over_generic_test_skill() -> None:
    original_root = registry.CUSTOM_SKILL_ROOT
    original_llm_method = LLMService.generate_skill_augmented_reply

    with tempfile.TemporaryDirectory() as temp_dir:
        custom_root = Path(temp_dir)
        prompt_only_dir = custom_root / "text-document-processor"
        prompt_only_dir.mkdir(parents=True, exist_ok=True)
        (prompt_only_dir / "SKILL.md").write_text(
            """---
name: text-document-processor
description: Use this skill when the user asks to process text documents.
---

# Text Document Processor Skill

请优先处理翻译、总结、对照、提炼、整理成 Markdown 等文本任务。
""",
            encoding="utf-8",
        )

        executable_dir = custom_root / "agent_skill_upload_test_v1"
        executable_dir.mkdir(parents=True, exist_ok=True)
        (executable_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "name": "agent-skill-upload-test",
                    "display_name": "Agent Skill Upload Test",
                    "version": "1.0.0",
                    "description": "A safe diagnostic Skill package for testing whether an Agent can discover, enable, and use an uploaded Skill.",
                    "triggers": ["测试上传Skill", "skill-handshake", "Skill握手测试", "使用上传Skill自检"],
                    "capabilities": ["skill_discovery_test", "instruction_following_test"],
                    "expected_markers": ["SKILL_UPLOAD_TEST_OK_v1", "SKILL_SCRIPT_EXEC_OK_v1"],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (executable_dir / "SKILL.md").write_text(
            "# Agent Skill Upload Test\n\n当消息提到上传 skill、自检、握手时，请输出 SKILL_UPLOAD_TEST_OK_v1。",
            encoding="utf-8",
        )
        scripts_dir = executable_dir / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        (scripts_dir / "skill_test.py").write_text(
            "import json\nprint(json.dumps({'marker':'SKILL_SCRIPT_EXEC_OK_v1','script_executed':True}, ensure_ascii=False))",
            encoding="utf-8",
        )

        docx_path = custom_root / "sample.docx"
        docx_path.write_bytes(_make_minimal_docx_bytes("这是需要总结的文档正文。核心观点是效率提升。"))

        try:
            registry.CUSTOM_SKILL_ROOT = custom_root

            def _fake_generate_skill_augmented_reply(self, *, skill_context: str, user_message: str, conversation_context: dict | None = None) -> dict:
                excerpt = str((conversation_context or {}).get("document_excerpt") or "")
                return {
                    "success": True,
                    "reply": f"提示词型文档 Skill 已处理：{user_message} | {excerpt}",
                    "error_message": None,
                    "raw_response": {"skill_context_preview": skill_context[:120]},
                    "warnings": [],
                }

            LLMService.generate_skill_augmented_reply = _fake_generate_skill_augmented_reply

            client = TestClient(app)
            with docx_path.open("rb") as fh:
                response = client.post(
                    "/api/agent/chat",
                    files={"file": ("sample.docx", fh, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
                    data={"message": "请使用文本文档处理 skill，总结这篇文档的核心观点、关键词和结论。", "debug": "true"},
                )
            payload = response.json()
            assert response.status_code == 200
            assert payload["success"] is True
            assert payload["skill_name"] == "text-document-processor"
            assert payload["skill_mode"] == "prompt_only"
            assert payload["error_message"] is None
            assert "提示词型文档 Skill 已处理" in payload["reply"]
            assert "这是需要总结的文档正文" in payload["reply"]
        finally:
            registry.CUSTOM_SKILL_ROOT = original_root
            LLMService.generate_skill_augmented_reply = original_llm_method


if __name__ == "__main__":
    test_prompt_only_skill_upload_and_chat_flow()
    test_invalid_skill_upload_rejects_readme_only_package()
    test_delete_uploaded_skill_accepts_discovered_runtime_name_for_legacy_record()
    test_prompt_only_skill_wins_docx_route_over_generic_test_skill()
    print("prompt-only skill flow tests passed")
