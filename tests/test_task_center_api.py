from pathlib import Path
import sys

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.agent import agent_router
from backend.api import workspace_api
from backend.main import app
import backend.services.task_trace_manager as task_trace_module


def _patch_task_services(tmp_path, monkeypatch):
    sandbox_root = PROJECT_ROOT / ".pytest-tmp" / f"{tmp_path.name}_task_center"
    workspace_root = sandbox_root / "workspace"
    task_index = sandbox_root / "storage" / "task_index.json"
    file_index = sandbox_root / "storage" / "file_index.json"
    monkeypatch.setattr(task_trace_module, "TASK_INDEX_PATH", task_index)
    for manager in (
        workspace_api.workspace_manager,
        workspace_api.task_trace_manager.workspace_manager,
        agent_router.workspace_manager,
        agent_router.task_trace_manager.workspace_manager,
    ):
        monkeypatch.setattr(manager, "root", workspace_root)
        monkeypatch.setattr(manager.file_catalog, "index_path", file_index)
    monkeypatch.setattr(workspace_api.task_trace_manager, "workspace_manager", workspace_api.workspace_manager)
    monkeypatch.setattr(agent_router.task_trace_manager, "workspace_manager", agent_router.workspace_manager)


def test_task_list_detail_and_skill_logs(tmp_path, monkeypatch):
    _patch_task_services(tmp_path, monkeypatch)
    trace_manager = workspace_api.task_trace_manager
    workspace_api.workspace_manager.create_workspace("tester", "task-center")
    output_file = workspace_api.workspace_manager.save_output_file("tester", "task-center", "result.txt", "analysis ok")

    task = trace_manager.create_task(
        user_id="tester",
        conversation_id="task-center",
        intent="raman_predict_report",
        input_message="生成报告",
        input_files=[{"file_id": "input-1", "filename": "sample.csv"}],
    )
    trace_manager.record_skill_run(
        task_id=task["task_id"],
        skill_name="raman_spectroscopy_skill",
        ability_name="predict_methanol_concentration",
        input_files=[{"file_id": "input-1", "filename": "sample.csv"}],
        output_files=[output_file],
        status="success",
        raw_result_summary="分析完成",
        input_summary="sample.csv",
    )

    client = TestClient(app)
    listed = client.get("/api/tasks", params={"user_id": "tester", "workspace_id": "task-center"})
    assert listed.status_code == 200
    listed_payload = listed.json()
    assert listed_payload["total"] >= 1
    assert listed_payload["tasks"][0]["task_type"] == "raman_predict_report"
    assert listed_payload["tasks"][0]["result_download_url"]

    detail = client.get(f"/api/tasks/{task['task_id']}")
    assert detail.status_code == 200
    detail_payload = detail.json()
    assert detail_payload["task_id"] == task["task_id"]
    assert detail_payload["task"]["task_id"] == task["task_id"]
    assert detail_payload["task_type"] == "raman_predict_report"

    logs = client.get("/api/agent/skills/logs", params={"user_id": "tester", "conversation_id": "task-center", "limit": 10})
    assert logs.status_code == 200
    log_payload = logs.json()
    assert log_payload["total"] >= 1
    assert log_payload["logs"][0]["skill_name"] == "raman_spectroscopy_skill"
    assert log_payload["logs"][0]["capability"] == "predict_methanol_concentration"
