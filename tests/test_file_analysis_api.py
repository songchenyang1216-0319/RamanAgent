from __future__ import annotations

from fastapi.testclient import TestClient

from backend.api import file_analysis_api
from backend.main import app


def test_legacy_agent_analyze_file_delegates_and_marks_deprecated(monkeypatch) -> None:
    async def fake_analyze_upload(*, file, request):
        return {
            "success": True,
            "session_id": request.conversation_id or request.session_id,
            "message": request.message,
            "saved_file": "storage/workspaces/demo/input.csv",
            "skill_name": "raman_spectroscopy_skill",
        }

    monkeypatch.setattr(file_analysis_api.service, "analyze_upload", fake_analyze_upload)

    response = TestClient(app).post(
        "/api/agent/analyze-file",
        data={"message": "分析 Raman 文件", "conversation_id": "conv-file-compat"},
        files={"file": ("sample.csv", b"x,y\n1,2\n", "text/csv")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["session_id"] == "conv-file-compat"
    assert payload["skill_name"] == "raman_spectroscopy_skill"
    assert response.headers["Deprecation"] == "true"
    assert response.headers["Link"] == '</api/files/analyze>; rel="successor-version"'


def test_files_analyze_uses_file_analysis_service_without_deprecation_header(monkeypatch) -> None:
    async def fake_analyze(*, request, is_admin=False):
        return {
            "success": True,
            "session_id": request.conversation_id,
            "file_ids": request.file_ids,
            "is_admin": is_admin,
        }

    monkeypatch.setattr(file_analysis_api.service, "analyze", fake_analyze)

    response = TestClient(app).post(
        "/api/files/analyze",
        json={
            "message": "请分析已上传文件",
            "conversation_id": "conv-file-api",
            "file_ids": ["file-a"],
            "user_id": "explicit-user",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["session_id"] == "conv-file-api"
    assert payload["file_ids"] == ["file-a"]
    assert "Deprecation" not in response.headers


def test_files_analyze_maps_missing_file_to_structured_404(monkeypatch) -> None:
    from backend.services.file_analysis_service import AgentFileNotFoundError

    async def fake_analyze(*, request, is_admin=False):
        raise AgentFileNotFoundError("missing")

    monkeypatch.setattr(file_analysis_api.service, "analyze", fake_analyze)

    response = TestClient(app).post(
        "/api/files/analyze",
        json={"message": "分析", "conversation_id": "conv-missing", "file_ids": ["missing"]},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["error_code"] == "FILE_NOT_FOUND"
