from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.main import app
import backend.skills.registry as registry
from backend.services.llm_service import LLMService


def test_orchestrator_general_chat_routes_to_model(monkeypatch):
    monkeypatch.setattr(
        LLMService,
        "generate_general_reply",
        lambda self, message, system_context=None: {
            "success": True,
            "reply": "你好，我是 RamanAgent。",
            "error_message": None,
            "model_info": self.get_current_model_info(),
        },
    )
    client = TestClient(app)
    payload = client.post("/api/agent/chat", json={"message": "你好，你是谁？"}).json()
    assert payload["success"] is True
    assert payload["category"] == "general_chat"
    assert payload["route"] == "model"
    assert payload["reply"] == "你好，我是 RamanAgent。"


def test_orchestrator_csv_analysis_routes_to_tool(tmp_path):
    path = tmp_path / "orders.csv"
    pd.DataFrame(
        {
            "province": ["上海", "北京", None],
            "sales": [10, 20, 30],
        }
    ).to_csv(path, index=False, encoding="utf-8")
    client = TestClient(app)
    payload = client.post(
        "/api/agent/chat",
        data={"message": "请分析这个表格的列名、缺失值和基本统计信息。"},
        files={"file": (path.name, path.read_bytes(), "text/csv")},
    ).json()
    assert payload["success"] is True
    assert payload["intent"] == "csv_analysis"
    assert payload["route"] == "tool"
    assert payload["tool_name"] == "csv_tool"
    assert "列名" in payload["reply"]
    assert "缺失值统计" in payload["reply"]


def test_orchestrator_raman_question_success(monkeypatch):
    monkeypatch.setattr(
        LLMService,
        "generate_general_reply",
        lambda self, message, system_context=None: {
            "success": True,
            "reply": "基线校正用于去除背景漂移，SG 平滑用于降低高频噪声。",
            "error_message": None,
            "model_info": self.get_current_model_info(),
        },
    )
    client = TestClient(app)
    payload = client.post("/api/agent/chat", json={"message": "请解释 Raman 光谱中的基线校正和 SG 平滑。"}).json()
    assert payload["success"] is True
    assert payload["intent"] == "raman_analysis"
    assert payload["route"] in {"model", "skill", "hybrid"}
    assert "基线校正" in payload["reply"]


def test_orchestrator_model_failure_returns_error(monkeypatch):
    monkeypatch.setattr(
        LLMService,
        "generate_general_reply",
        lambda self, message, system_context=None: {
            "success": False,
            "reply": "",
            "error_message": "模拟模型 API 失败",
            "model_info": self.get_current_model_info(),
        },
    )
    client = TestClient(app)
    payload = client.post("/api/agent/chat", json={"message": "请总结一下 Agent 架构的核心思想。"}).json()
    assert payload["success"] is False
    assert payload["error_message"] == "模拟模型 API 失败"


def test_orchestrator_prompt_only_skill_routes_correctly(monkeypatch):
    original_root = registry.CUSTOM_SKILL_ROOT
    original_llm = LLMService.generate_skill_augmented_reply
    with tempfile.TemporaryDirectory() as temp_dir:
        custom_root = Path(temp_dir)
        package_dir = custom_root / "text-document-processor"
        package_dir.mkdir(parents=True, exist_ok=True)
        (package_dir / "SKILL.md").write_text(
            """---
name: text-document-processor
description: Use this skill when the user asks to process text documents.
---

# Text Document Processor

请优先执行翻译、总结和整理。
""",
            encoding="utf-8",
        )
        (package_dir / "README.md").write_text("# README", encoding="utf-8")
        registry.CUSTOM_SKILL_ROOT = custom_root
        monkeypatch.setattr(
            LLMService,
            "generate_skill_augmented_reply",
            lambda self, *, skill_context, user_message, conversation_context=None: {
                "success": True,
                "reply": "这是一个测试。",
                "error_message": None,
                "raw_response": {"mock": True},
                "warnings": [],
            },
        )
        client = TestClient(app)
        payload = client.post("/api/agent/chat", json={"message": "请把这段英文翻译成中文：This is a test."}).json()
        assert payload["success"] is True
        assert payload["skill_name"] == "text-document-processor"
        assert payload["skill_mode"] == "prompt_only"
        assert payload["route"] == "skill"
    registry.CUSTOM_SKILL_ROOT = original_root
    LLMService.generate_skill_augmented_reply = original_llm


def test_orchestrator_executable_skill_routes_correctly():
    original_root = registry.CUSTOM_SKILL_ROOT
    with tempfile.TemporaryDirectory() as temp_dir:
        custom_root = Path(temp_dir)
        package_dir = custom_root / "agent_skill_upload_test_v1"
        package_dir.mkdir(parents=True, exist_ok=True)
        (package_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "name": "agent-skill-upload-test",
                    "display_name": "Agent Skill Upload Test",
                    "version": "1.0.0",
                    "description": "用于验证上传 Skill 是否会被发现和执行。",
                    "triggers": ["Skill握手测试", "使用上传Skill自检"],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (package_dir / "SKILL.md").write_text("# Agent Skill Upload Test", encoding="utf-8")
        scripts_dir = package_dir / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)
        (scripts_dir / "skill_test.py").write_text(
            "import json\nprint(json.dumps({'marker':'SKILL_SCRIPT_EXEC_OK_v1','script_executed':True}, ensure_ascii=False))",
            encoding="utf-8",
        )
        registry.CUSTOM_SKILL_ROOT = custom_root
        client = TestClient(app)
        payload = client.post("/api/agent/chat", json={"message": "请执行一次 Skill 握手自检。"}).json()
        assert payload["success"] is True
        assert payload["skill_name"] == "agent-skill-upload-test"
        assert payload["skill_mode"] == "executable"
    registry.CUSTOM_SKILL_ROOT = original_root
