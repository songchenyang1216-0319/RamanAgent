from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.skills.registry import execute_skill


def test_table_analysis_skill_entry_executes_delegate(tmp_path: Path):
    path = tmp_path / "orders.csv"
    pd.DataFrame({"city": ["上海", "北京"], "sales": [10, 20]}).to_csv(path, index=False, encoding="utf-8")
    result = execute_skill("table-analysis", action_name="basic_statistics", file_path=str(path), message="做基础统计")
    assert result.success is True
    assert result.skill_name == "table-analysis"
    assert result.data["delegate_skill_name"] == "data-analysis-skill"


def test_disabled_table_analysis_returns_clear_error(monkeypatch, tmp_path: Path):
    path = tmp_path / "orders.csv"
    pd.DataFrame({"city": ["上海"], "sales": [10]}).to_csv(path, index=False, encoding="utf-8")
    real_loader = __import__("backend.skills.registry", fromlist=["_load_skills_config"])._load_skills_config

    def fake_load():
        config, error = real_loader()
        config["skills"]["table-analysis"]["enabled"] = False
        return config, error

    monkeypatch.setattr("backend.skills.registry._load_skills_config", fake_load)
    result = execute_skill("table-analysis", action_name="basic_statistics", file_path=str(path), message="做基础统计")
    assert result.success is False
    assert "当前已禁用" in "；".join(result.errors)
