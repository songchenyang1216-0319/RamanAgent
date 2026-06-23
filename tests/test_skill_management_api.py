from __future__ import annotations

from fastapi.testclient import TestClient

from backend.api import agent_skill_compat_api, skill_api
from backend.main import app
from backend.services.skill_service import SkillManagementService


def test_skill_service_delegates_registry_functions(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr("backend.services.skill_service.get_skill", lambda name: object())
    monkeypatch.setattr("backend.services.skill_service.get_action", lambda skill, action: object())
    monkeypatch.setattr(
        "backend.services.skill_service.set_skill_enabled",
        lambda skill, enabled: calls.append(("skill", enabled)) or {"success": True, "skill": skill, "enabled": enabled},
    )
    monkeypatch.setattr(
        "backend.services.skill_service.set_action_enabled",
        lambda skill, action, enabled: calls.append(("action", enabled)) or {"success": True, "skill": skill, "action": action, "enabled": enabled},
    )

    service = SkillManagementService()

    assert service.set_skill_enabled("demo", False)["enabled"] is False
    assert service.set_action_enabled("demo", "run", True)["enabled"] is True
    assert calls == [("skill", False), ("action", True)]


def test_skill_service_rejects_builtin_skill_delete(monkeypatch) -> None:
    class BuiltinSkill:
        source = "builtin"

    monkeypatch.setattr("backend.services.skill_service.list_uploaded_skills", lambda: [])
    monkeypatch.setattr("backend.services.skill_service.get_skill", lambda name: BuiltinSkill())

    service = SkillManagementService()

    try:
        service.delete_skill("builtin")
    except ValueError as exc:
        assert "内置 Skill 不能删除" in str(exc)
    else:
        raise AssertionError("应拒绝删除内置 Skill")


def test_new_skill_api_routes_delegate_without_deprecation(monkeypatch) -> None:
    monkeypatch.setattr(skill_api.skill_service, "list_skills", lambda include_actions=True: {"success": True, "skills": [], "include_actions": include_actions})

    response = TestClient(app).get("/api/skills")

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["include_actions"] is True
    assert "Deprecation" not in response.headers


def test_legacy_agent_skill_api_routes_delegate_with_deprecation(monkeypatch) -> None:
    monkeypatch.setattr(agent_skill_compat_api.skill_service, "list_skills", lambda include_actions=True: {"success": True, "skills": []})

    response = TestClient(app).get("/api/agent/skills")

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.headers["Deprecation"] == "true"
    assert response.headers["Link"] == '</api/skills>; rel="successor-version"'


def test_legacy_agent_skill_upload_uses_service_and_deprecation(monkeypatch) -> None:
    def fake_upload_skill(*, filename, content):
        return {"success": True, "filename": filename, "size": len(content)}

    monkeypatch.setattr(agent_skill_compat_api.skill_service, "upload_skill", fake_upload_skill)

    response = TestClient(app).post(
        "/api/agent/skills/upload",
        files={"file": ("demo.zip", b"zip-content", "application/zip")},
    )

    assert response.status_code == 200
    assert response.json()["filename"] == "demo.zip"
    assert response.headers["Deprecation"] == "true"
