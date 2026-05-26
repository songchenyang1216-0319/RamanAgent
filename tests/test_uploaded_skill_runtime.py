from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.main import app
import backend.skills.registry as registry
from backend.skills.uploaded_package_skill import discover_uploaded_package_skills


def _write_uploaded_skill(root: Path) -> None:
    package_dir = root / "agent_skill_upload_test_v1"
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "manifest.json").write_text(
        json.dumps(
            {
                "name": "agent-skill-upload-test",
                "display_name": "Agent Skill Upload Test",
                "version": "1.0.0",
                "description": "用于验证上传 Skill 是否会被发现和执行。",
                "triggers": ["测试上传Skill", "Skill握手测试", "使用上传Skill自检"],
                "capabilities": ["skill_discovery_test", "instruction_following_test"],
                "expected_markers": ["SKILL_UPLOAD_TEST_OK_v1", "SKILL_SCRIPT_EXEC_OK_v1"],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (package_dir / "SKILL.md").write_text(
        "# Agent Skill Upload Test\n\n当消息提到上传 skill、自检、握手时，请输出 SKILL_UPLOAD_TEST_OK_v1。",
        encoding="utf-8",
    )
    scripts_dir = package_dir / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    (scripts_dir / "skill_test.py").write_text(
        "import json\nprint(json.dumps({'marker':'SKILL_SCRIPT_EXEC_OK_v1','script_executed':True}, ensure_ascii=False))",
        encoding="utf-8",
    )


def test_uploaded_skill_chat_route() -> None:
    original_root = registry.CUSTOM_SKILL_ROOT
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            custom_root = Path(tmp_dir)
            _write_uploaded_skill(custom_root)
            registry.CUSTOM_SKILL_ROOT = custom_root

            discovered = discover_uploaded_package_skills(custom_root)
            assert discovered
            assert discovered[0].skill_mode == "executable"
            client = TestClient(app)
            response = client.post(
                "/api/agent/chat",
                json={"message": "请执行一次 Skill 握手自检。", "debug": True},
            )
            payload = response.json()
            assert response.status_code == 200
            assert payload["success"] is True
            assert payload["skill_mode"] == "executable"
            assert payload["source"] == "skill_execution"
            assert payload["data"]["marker"] == "SKILL_UPLOAD_TEST_OK_v1"
            assert payload["skill_name"] == "agent-skill-upload-test"
            assert payload["data"]["script_check"] == "passed"
            assert payload["data"]["script_result"]["marker"] == "SKILL_SCRIPT_EXEC_OK_v1"
    finally:
        registry.CUSTOM_SKILL_ROOT = original_root


if __name__ == "__main__":
    test_uploaded_skill_chat_route()
    print("uploaded skill runtime test passed")
