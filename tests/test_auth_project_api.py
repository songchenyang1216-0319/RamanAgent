from pathlib import Path
import sys

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.api import auth_dependencies, file_api, project_api, report_api, workspace_api, methanol_api
from backend.main import app
import backend.services.task_trace_manager as task_trace_module


def _configure_phase2_sandbox(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_SECRET", "phase2_auth_test_secret_value_32_chars")
    monkeypatch.setenv("DEFAULT_ADMIN_PASSWORD", "ProdAdminPass123!")
    monkeypatch.setenv("AGENT_RUNTIME_MODE", "graph")
    monkeypatch.setenv("VECTOR_DB_PROVIDER", "chroma")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "local")
    sandbox_root = PROJECT_ROOT / ".pytest-tmp" / f"{tmp_path.name}_phase2_auth"
    workspace_root = sandbox_root / "workspace"
    storage_root = sandbox_root / "storage"
    file_index = storage_root / "file_index.json"
    task_index = storage_root / "task_index.json"
    users_path = storage_root / "users.json"
    tokens_path = storage_root / "auth_tokens.json"
    projects_path = storage_root / "projects.json"
    reports_path = storage_root / "reports.json"
    monkeypatch.setattr(task_trace_module, "TASK_INDEX_PATH", task_index)
    monkeypatch.setattr(auth_dependencies.user_service, "users_path", users_path)
    monkeypatch.setattr(auth_dependencies.user_service, "tokens_path", tokens_path)

    for manager in (
        file_api.workspace_manager,
        workspace_api.workspace_manager,
        workspace_api.task_trace_manager.workspace_manager,
        project_api.workspace_manager,
        project_api.task_trace_manager.workspace_manager,
        report_api.workspace_manager,
        report_api.task_trace_manager.workspace_manager,
        methanol_api.workspace_manager,
        methanol_api.task_trace_manager.workspace_manager,
        methanol_api.batch_analysis_service.workspace_manager,
        methanol_api.batch_analysis_service.task_trace_manager.workspace_manager,
        methanol_api.batch_analysis_service.project_service.task_trace_manager.workspace_manager,
        report_api.project_service.task_trace_manager.workspace_manager,
        report_api.report_export_service.task_trace_manager.workspace_manager,
    ):
        monkeypatch.setattr(manager, "root", workspace_root)
        monkeypatch.setattr(manager.file_catalog, "index_path", file_index)

    for catalog in (
        file_api.file_catalog,
        project_api.project_service.file_catalog,
        report_api.file_catalog,
        report_api.project_service.file_catalog,
        report_api.report_export_service.file_catalog,
        report_api.report_registry.file_catalog,
        methanol_api.file_catalog,
        methanol_api.batch_analysis_service.file_catalog,
        methanol_api.batch_analysis_service.project_service.file_catalog,
        methanol_api.batch_analysis_service.report_export_service.file_catalog,
    ):
        monkeypatch.setattr(catalog, "index_path", file_index)

    monkeypatch.setattr(project_api.project_service, "projects_path", projects_path)
    monkeypatch.setattr(report_api.project_service, "projects_path", projects_path)
    monkeypatch.setattr(report_api.report_export_service.project_service, "projects_path", projects_path)
    monkeypatch.setattr(methanol_api.batch_analysis_service.project_service, "projects_path", projects_path)

    monkeypatch.setattr(project_api.report_registry, "reports_path", reports_path)
    monkeypatch.setattr(project_api.project_service.report_service, "reports_path", reports_path)
    monkeypatch.setattr(report_api.report_registry, "reports_path", reports_path)
    monkeypatch.setattr(report_api.project_service.report_service, "reports_path", reports_path)
    monkeypatch.setattr(report_api.report_export_service.report_registry, "reports_path", reports_path)


def _register_and_login(client: TestClient, username: str, password: str = "UnitTestPass123!") -> dict:
    response = client.post("/api/auth/register", json={"username": username, "password": password})
    assert response.status_code == 200
    return response.json()


def test_auth_register_login_and_project_binding(tmp_path, monkeypatch):
    _configure_phase2_sandbox(tmp_path, monkeypatch)
    client = TestClient(app)

    registered = _register_and_login(client, "demo_user")
    token = registered["token"]
    headers = {"Authorization": f"Bearer {token}"}

    stored_user = auth_dependencies.user_service.get_user_by_username("demo_user")
    assert stored_user is not None
    assert stored_user["password_hash"] != "UnitTestPass123!"
    assert "UnitTestPass123!" not in stored_user["password_hash"]

    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["user"]["username"] == "demo_user"

    project_response = client.post(
        "/api/projects",
        headers=headers,
        json={"name": "甲醇浓度检测实验", "description": "用于项目绑定测试"},
    )
    assert project_response.status_code == 200
    project_id = project_response.json()["project"]["project_id"]

    upload = client.post(
        "/api/files/upload",
        headers=headers,
        data={"conversation_id": "phase2-auth", "project_id": project_id},
        files={"file": ("sample.csv", b"400,1\n401,2\n402,3\n", "text/csv")},
    )
    assert upload.status_code == 200
    file_id = upload.json()["file_id"]

    file_detail = client.get(f"/api/files/{file_id}", headers=headers)
    assert file_detail.status_code == 200
    assert file_detail.json()["file"]["project_id"] == project_id

    project_files = client.get(f"/api/projects/{project_id}/files", headers=headers)
    assert project_files.status_code == 200
    assert project_files.json()["total"] == 1

    project_list = client.get("/api/projects", headers=headers)
    assert project_list.status_code == 200
    assert project_list.json()["projects"][0]["file_count"] == 1


def test_protected_endpoints_require_login_and_isolate_files(tmp_path, monkeypatch):
    _configure_phase2_sandbox(tmp_path, monkeypatch)
    client = TestClient(app)

    unauthorized = client.get("/api/projects")
    assert unauthorized.status_code == 401

    first_user = _register_and_login(client, "owner_user")
    owner_headers = {"Authorization": f"Bearer {first_user['token']}"}
    second_user = _register_and_login(client, "guest_user")
    guest_headers = {"Authorization": f"Bearer {second_user['token']}"}

    upload = client.post(
        "/api/files/upload",
        headers=owner_headers,
        data={"conversation_id": "owner-space"},
        files={"file": ("owner.csv", b"400,1\n401,2\n", "text/csv")},
    )
    assert upload.status_code == 200
    file_id = upload.json()["file_id"]

    forbidden = client.get(f"/api/files/{file_id}", headers=guest_headers)
    assert forbidden.status_code == 404

    empty_list = client.get("/api/files", headers=guest_headers)
    assert empty_list.status_code == 200
    assert empty_list.json()["total"] == 0
