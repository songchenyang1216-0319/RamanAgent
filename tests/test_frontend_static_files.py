from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = PROJECT_ROOT / "frontend"


def test_frontend_static_files_exist():
    assert FRONTEND_DIR.exists()
    assert (FRONTEND_DIR / "index.html").exists()
    assert (FRONTEND_DIR / "app.js").exists()
    assert (FRONTEND_DIR / "style.css").exists()
    assert (FRONTEND_DIR / "js" / "api.js").exists()


def test_frontend_references_agent_endpoints():
    index_text = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    api_text = (FRONTEND_DIR / "js" / "api.js").read_text(encoding="utf-8")
    app_text = (FRONTEND_DIR / "app.js").read_text(encoding="utf-8")

    assert "/api/agent/analyze-file" in api_text
    assert "/api/agent/chat" in api_text
    assert "chatMessages" in index_text
    assert "professional_analysis" in app_text
    assert "renderUploadedSkillResult" in app_text
    assert "前后叠加对比" in app_text
    assert "结果摘要" in app_text
