from pathlib import Path
import sys

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.api import file_api
from backend.main import app


def _patch_file_services(tmp_path, monkeypatch):
    sandbox_root = PROJECT_ROOT / ".pytest-tmp" / f"{tmp_path.name}_file_center"
    workspace_root = sandbox_root / "workspace"
    file_index = sandbox_root / "storage" / "file_index.json"
    monkeypatch.setattr(file_api.workspace_manager, "root", workspace_root)
    monkeypatch.setattr(file_api.workspace_manager.file_catalog, "index_path", file_index)
    monkeypatch.setattr(file_api.file_catalog, "index_path", file_index)


def test_file_center_endpoints(tmp_path, monkeypatch):
    _patch_file_services(tmp_path, monkeypatch)
    client = TestClient(app)

    response = client.post(
        "/api/files/upload",
        data={"user_id": "tester", "conversation_id": "file-center"},
        files={"file": ("sample.csv", b"400,1\n401,2\n402,3\n", "text/csv")},
    )
    assert response.status_code == 200
    uploaded = response.json()
    file_id = uploaded["file_id"]

    listed = client.get("/api/files", params={"user_id": "tester", "workspace_id": "file-center"})
    assert listed.status_code == 200
    payload = listed.json()
    assert payload["total"] == 1
    assert payload["files"][0]["original_filename"] == "sample.csv"

    preview = client.get(f"/api/files/{file_id}/preview")
    assert preview.status_code == 200
    preview_payload = preview.json()
    assert preview_payload["preview_type"] == "csv"
    assert "400,1" in preview_payload["content"]

    download = client.get(f"/api/files/{file_id}/download")
    assert download.status_code == 200
    assert b"400,1" in download.content

    deleted = client.delete(f"/api/files/{file_id}")
    assert deleted.status_code == 200
    assert deleted.json()["success"] is True

    listed_again = client.get("/api/files", params={"user_id": "tester", "workspace_id": "file-center"})
    assert listed_again.status_code == 200
    assert listed_again.json()["total"] == 0
