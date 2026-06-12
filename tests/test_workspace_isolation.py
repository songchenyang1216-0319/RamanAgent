from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.services.workspace_manager import WorkspaceManager


def test_workspace_active_files_are_isolated_by_conversation(tmp_path: Path):
    manager = WorkspaceManager(root=tmp_path)
    manager.update_active_files("user-a", "conv-a", [{"file_id": "a", "filename": "a.csv"}])
    manager.update_active_files("user-a", "conv-b", [{"file_id": "b", "filename": "b.pdf"}])
    assert manager.read_active_files("user-a", "conv-a")[0]["filename"] == "a.csv"
    assert manager.read_active_files("user-a", "conv-b")[0]["filename"] == "b.pdf"
