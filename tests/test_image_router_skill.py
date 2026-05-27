from __future__ import annotations

import io
from pathlib import Path
import sys

from fastapi.testclient import TestClient
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.agent.agent_router import _is_image_file_suffix, _select_skill_route
from backend.main import app
from backend.skills.registry import execute_skill, list_skills


def _make_image_bytes(fmt: str = "PNG", color: tuple[int, int, int] = (90, 140, 210)) -> bytes:
    image = Image.new("RGB", (160, 120), color=color)
    buffer = io.BytesIO()
    image.save(buffer, format=fmt)
    return buffer.getvalue()


def _write_temp_image(tmp_path: Path, name: str = "sample.png", fmt: str = "PNG") -> Path:
    path = tmp_path / name
    path.write_bytes(_make_image_bytes(fmt=fmt))
    return path


def _mock_no_vision(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.skills.image_router_skill.ImageRouterSkill._resolve_model_context",
        lambda self, **kwargs: {
            "current_model": {
                "provider_id": "qwen",
                "provider_name": "通义千问",
                "model_id": "qwen-plus",
                "model_name": "qwen-plus",
                "supports_vision": False,
            },
            "available_vision_models": [],
        },
    )


def _mock_with_other_vision(monkeypatch) -> None:
    monkeypatch.setattr(
        "backend.skills.image_router_skill.ImageRouterSkill._resolve_model_context",
        lambda self, **kwargs: {
            "current_model": {
                "provider_id": "qwen",
                "provider_name": "通义千问",
                "model_id": "qwen-plus",
                "model_name": "qwen-plus",
                "supports_vision": False,
            },
            "available_vision_models": [
                {
                    "provider_id": "qwen",
                    "provider_name": "通义千问",
                    "model_id": "qwen-vl-plus",
                    "display_name": "通义千问 · qwen-vl-plus",
                    "supports_vision": True,
                }
            ],
        },
    )


def test_image_router_skill_is_listed():
    payload = list_skills(include_actions=True)
    names = {item.get("name") for item in payload.get("skills") or []}
    assert "image-router-skill" in names
    target = next(item for item in payload["skills"] if item.get("name") == "image-router-skill")
    action_names = {action.get("name") for action in target.get("actions") or []}
    assert "classify_image_type" in action_names
    assert "ocr_extract_text" in action_names


def test_common_image_suffixes_are_recognized():
    for suffix in (".png", ".jpg", ".jpeg", ".webp"):
        assert _is_image_file_suffix(suffix) is True


def test_image_route_does_not_go_to_document_or_raman():
    matched_skill, matched_action, route_info = _select_skill_route("帮我看看这张图片", has_file=True, file_suffix=".png")
    assert matched_skill == "image-router-skill"
    assert matched_action == "classify_image_type"
    assert route_info["reason"].startswith("image_router:")


def test_raman_keywords_route_to_raman_image_action(tmp_path, monkeypatch):
    _mock_no_vision(monkeypatch)
    image_path = _write_temp_image(tmp_path, "raman.png")
    result = execute_skill("image-router-skill", action_name="classify_image_type", file_path=str(image_path), message="帮我分析这张拉曼光谱图，看看峰位和基线")
    assert result.action_name == "analyze_raman_spectrum_image"
    assert result.data["image_type"] == "RAMAN_SPECTRUM_IMAGE"


def test_screenshot_keywords_route_to_screenshot_action(tmp_path, monkeypatch):
    _mock_no_vision(monkeypatch)
    image_path = _write_temp_image(tmp_path, "screen.png")
    result = execute_skill("image-router-skill", action_name="classify_image_type", file_path=str(image_path), message="这个页面报错是什么原因")
    assert result.action_name == "analyze_screenshot"
    assert result.data["image_type"] in {"SCREENSHOT", "ERROR_SCREENSHOT"}


def test_ocr_keywords_route_to_ocr_action(tmp_path, monkeypatch):
    _mock_no_vision(monkeypatch)
    image_path = _write_temp_image(tmp_path, "ocr.png")
    result = execute_skill("image-router-skill", action_name="classify_image_type", file_path=str(image_path), message="提取图片里的文字，并翻译图片")
    assert result.action_name == "ocr_extract_text"
    assert result.data["image_type"] == "TEXT_IMAGE"


def test_chart_keywords_route_to_chart_action(tmp_path, monkeypatch):
    _mock_no_vision(monkeypatch)
    image_path = _write_temp_image(tmp_path, "figure.png")
    result = execute_skill("image-router-skill", action_name="classify_image_type", file_path=str(image_path), message="帮我解释一下这张论文 Figure 曲线图")
    assert result.action_name == "analyze_chart_or_figure"
    assert result.data["image_type"] == "CHART_OR_FIGURE"


def test_no_vision_model_returns_friendly_degrade(tmp_path, monkeypatch):
    _mock_no_vision(monkeypatch)
    image_path = _write_temp_image(tmp_path, "photo.png")
    result = execute_skill("image-router-skill", action_name="classify_image_type", file_path=str(image_path), message="帮我看看这张图片主要是什么内容")
    assert result.success is True
    assert "当前没有可用视觉模型" in result.data["analysis_markdown"]
    assert "quality" in result.data


def test_disabled_image_router_skill_returns_friendly_prompt(monkeypatch):
    _mock_with_other_vision(monkeypatch)
    client = TestClient(app)

    real_loader = __import__("backend.skills.registry", fromlist=["_load_skills_config"])._load_skills_config

    def fake_load():
        config, error = real_loader()
        config["skills"]["image-router-skill"]["enabled"] = False
        return config, error

    monkeypatch.setattr("backend.skills.registry._load_skills_config", fake_load)
    response = client.post(
        "/api/agent/chat",
        data={"message": "帮我看看这张图片"},
        files={"file": ("sample.png", _make_image_bytes("PNG"), "image/png")},
    )
    payload = response.json()
    assert payload["success"] is False
    assert "image-router-skill 当前被禁用" in payload["reply"]


def test_disabled_image_sub_action_returns_friendly_prompt(monkeypatch):
    _mock_no_vision(monkeypatch)
    client = TestClient(app)

    real_loader = __import__("backend.skills.registry", fromlist=["_load_skills_config"])._load_skills_config

    def fake_load():
        config, error = real_loader()
        config["skills"]["image-router-skill"]["enabled"] = True
        config["skills"]["image-router-skill"]["actions"]["ocr_extract_text"] = False
        return config, error

    monkeypatch.setattr("backend.skills.registry._load_skills_config", fake_load)
    response = client.post(
        "/api/agent/chat",
        data={"message": "提取图片里的文字"},
        files={"file": ("sample.png", _make_image_bytes("PNG"), "image/png")},
    )
    payload = response.json()
    assert payload["success"] is False
    assert "ocr_extract_text" in payload["reply"]
    assert "禁用" in payload["reply"]


def test_corrupted_image_will_not_crash_backend(tmp_path, monkeypatch):
    _mock_no_vision(monkeypatch)
    broken_path = tmp_path / "broken.png"
    broken_path.write_bytes(b"not a real image")
    result = execute_skill("image-router-skill", action_name="classify_image_type", file_path=str(broken_path), message="帮我看图")
    assert result.success is False
    assert "无法正常读取" in result.summary


def test_quality_check_returns_core_fields(tmp_path):
    image_path = _write_temp_image(tmp_path, "quality.png")
    result = execute_skill("image-router-skill", action_name="image_quality_check", file_path=str(image_path), message="检测质量")
    quality = result.data["quality"]
    assert quality["width"] > 0
    assert quality["height"] > 0
    assert quality["format"]
    assert isinstance(quality["brightness"], float)
    assert isinstance(quality["contrast"], float)
    assert isinstance(quality["sharpness"], float)
