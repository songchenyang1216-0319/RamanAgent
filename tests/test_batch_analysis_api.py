from pathlib import Path
import sys

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.main import app
import backend.services.batch_analysis_service as batch_analysis_module

from tests.test_auth_project_api import _configure_phase2_sandbox, _register_and_login


def _mock_predict(path):
    if "bad" in Path(path).name:
        raise ValueError("坏样本无法分析")
    return {
        "final_prediction": 0.11,
        "unit": "%",
    }


def _mock_professional_analysis(path, _result):
    if "bad" in Path(path).name:
        raise ValueError("光谱质量异常")
    return {
        "success": True,
        "quality_analysis": {
            "overall_quality": "good",
            "quality_level": "good",
        },
        "peak_analysis": {
            "peaks": [{"wavenumber": 1030.0, "intensity": 1.0}],
        },
    }


def test_batch_analysis_continues_after_single_file_failure(tmp_path, monkeypatch):
    _configure_phase2_sandbox(tmp_path, monkeypatch)
    monkeypatch.setattr(batch_analysis_module, "predict_methanol", _mock_predict)
    monkeypatch.setattr(batch_analysis_module, "analyze_spectrum_professionally", _mock_professional_analysis)

    client = TestClient(app)
    user = _register_and_login(client, "batch_user")
    headers = {"Authorization": f"Bearer {user['token']}"}

    file_ids = []
    for name, content in (
        ("good.csv", b"400,1\n401,2\n"),
        ("bad.csv", b"400,9\n401,8\n"),
    ):
        response = client.post(
            "/api/files/upload",
            headers=headers,
            data={"conversation_id": "batch-space"},
            files={"file": (name, content, "text/csv")},
        )
        assert response.status_code == 200
        file_ids.append(response.json()["file_id"])

    batch = client.post(
        "/api/methanol/batch-analyze",
        headers=headers,
        json={
            "file_ids": file_ids,
            "options": {
                "generate_report": False,
                "export_formats": ["markdown"],
            },
        },
    )
    assert batch.status_code == 200
    payload = batch.json()
    task_id = payload["task_id"]
    summary = payload["summary"]
    assert summary["total_files"] == 2
    assert summary["success_count"] == 1
    assert summary["failed_count"] == 1
    assert any(item["status"] == "failed" for item in summary["items"])

    fetched_summary = client.get(f"/api/methanol/batch-tasks/{task_id}/summary", headers=headers)
    assert fetched_summary.status_code == 200
    assert fetched_summary.json()["summary"]["failed_count"] == 1

    csv_download = client.get(f"/api/methanol/batch-tasks/{task_id}/download-csv", headers=headers)
    assert csv_download.status_code == 200
    assert "文件名" in csv_download.content.decode("utf-8-sig")
