from pathlib import Path
import sys

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.api import report_api
from backend.main import app
import backend.services.report_export_service as report_export_module
import backend.services.report_registry_service as report_registry_module
import backend.services.report_service as report_service_module

from tests.test_auth_project_api import _configure_phase2_sandbox, _register_and_login


def _mock_predict(_path):
    return {
        "sample_file": "sample.csv",
        "sample_path": "workspace/demo/sample.csv",
        "model_version": "mock_v1",
        "svr_prediction": 0.12,
        "rf_prediction": 0.13,
        "fusion_prediction": 0.125,
        "final_prediction": 0.125,
        "unit": "%",
        "confidence": {"knn_distance": 0.08, "threshold": 0.12, "status": "可信度正常"},
        "model_disagreement": {
            "absolute_difference": 0.01,
            "relative_difference": 0.08,
            "warning": False,
            "message": "差异可接受",
        },
        "figures": {},
        "pipeline": ["统一波数轴", "SG平滑", "ALS去基线"],
    }


def _mock_professional_analysis(_path, _result):
    return {
        "success": True,
        "quality_analysis": {
            "overall_quality": "good",
            "quality_level": "good",
            "issues": [],
            "metrics": {"estimated_snr": 21.5, "baseline_drift_score": 0.1},
        },
        "baseline_analysis": {"success": True, "baseline_level": "normal", "warnings": []},
        "peak_analysis": {
            "success": True,
            "peaks": [{"rank": 1, "wavenumber": 1030.0, "intensity": 1.0, "prominence": 0.8}],
        },
        "professional_summary": {
            "conclusion": "当前样品可用于参考判断。",
            "risks": [],
            "suggestions": ["建议重复采样"],
            "ood_risk": {"level": "low", "score": 0.12, "warnings": []},
        },
    }


def test_report_export_and_permission(tmp_path, monkeypatch):
    _configure_phase2_sandbox(tmp_path, monkeypatch)
    reports_root = PROJECT_ROOT / ".pytest-tmp" / f"{tmp_path.name}_phase2_reports" / "reports"
    monkeypatch.setattr(report_service_module, "REPORT_DIR", reports_root)
    monkeypatch.setattr(report_export_module, "REPORT_DIR", reports_root)
    monkeypatch.setattr(report_registry_module, "REPORT_DIR", reports_root)
    monkeypatch.setattr(report_export_module, "predict_methanol", _mock_predict)
    monkeypatch.setattr(report_export_module, "analyze_spectrum_professionally", _mock_professional_analysis)

    client = TestClient(app)
    owner = _register_and_login(client, "report_owner")
    owner_headers = {"Authorization": f"Bearer {owner['token']}"}
    other = _register_and_login(client, "report_guest")
    other_headers = {"Authorization": f"Bearer {other['token']}"}

    upload = client.post(
        "/api/files/upload",
        headers=owner_headers,
        data={"conversation_id": "report-space"},
        files={"file": ("raman.csv", b"400,1\n401,3\n402,2\n", "text/csv")},
    )
    assert upload.status_code == 200
    file_id = upload.json()["file_id"]

    exported = client.post(
        "/api/reports/export",
        headers=owner_headers,
        json={"file_id": file_id, "formats": ["markdown", "docx"]},
    )
    assert exported.status_code == 200
    payload = exported.json()
    report_id = payload["report"]["report_id"]
    assert payload["report"]["markdown_path"]
    assert payload["report"]["docx_path"]

    reports = client.get("/api/reports", headers=owner_headers)
    assert reports.status_code == 200
    assert reports.json()["total"] == 1

    markdown_download = client.get(f"/api/reports/{report_id}/download", headers=owner_headers, params={"format": "markdown"})
    assert markdown_download.status_code == 200
    assert "text/markdown" in markdown_download.headers["content-type"]
    assert "Raman" in markdown_download.text

    forbidden = client.get(f"/api/reports/{report_id}/download", headers=other_headers, params={"format": "markdown"})
    assert forbidden.status_code == 404
