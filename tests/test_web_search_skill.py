from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.skills.registry import execute_skill
from backend.skills.web_search.web_search_skill import WebSearchSkill


def test_web_search_skill_missing_tavily_key(monkeypatch):
    monkeypatch.setenv("WEB_SEARCH_ENABLED", "true")
    monkeypatch.setenv("WEB_SEARCH_PROVIDER", "tavily")
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("WEB_SEARCH_FALLBACK_PROVIDER", raising=False)

    skill = WebSearchSkill()
    result = skill.run(action_name="search", query="联网查一下 Tavily 是什么")

    assert result.success is False
    assert result.skill_name == "web-search"
    assert result.action_name == "search"
    assert result.data["error_code"] == "WEB_SEARCH_FAILED"
    assert "TAVILY_API_KEY" in result.data["message"]
    assert result.data["items"] == []


def test_web_search_skill_success_with_mocked_provider(monkeypatch):
    monkeypatch.setenv("WEB_SEARCH_ENABLED", "true")
    monkeypatch.setenv("WEB_SEARCH_PROVIDER", "tavily")
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test-key")

    def fake_bundle(self, query, max_results=5):
        return {
            "query": query,
            "items": [
                {
                    "title": "Tavily 简介",
                    "url": "https://example.com/tavily",
                    "snippet": "Tavily 是一个联网搜索服务。",
                    "source": "tavily",
                    "score": 0.99,
                    "published_at": None,
                }
            ],
            "total": 1,
            "source": "tavily",
            "used_provider": "tavily",
            "answer": "Tavily 是一个联网搜索服务。",
            "request_id": "req-1",
            "response_time": 0.12,
            "search_depth": "basic",
            "include_answer": True,
            "include_raw_content": False,
            "include_images": False,
        }

    monkeypatch.setattr("backend.skills.web_search.providers.tavily_provider.TavilyProvider.search_bundle", fake_bundle)

    skill = WebSearchSkill()
    result = skill.run(action_name="search", query="联网查一下 Tavily 是什么")

    assert result.success is True
    assert result.skill_name == "web-search"
    assert result.action_name == "search"
    assert result.data["used_provider"] == "tavily"
    assert result.data["items"][0]["title"] == "Tavily 简介"
    assert result.data["answer"] == "Tavily 是一个联网搜索服务。"


def test_execute_skill_web_search_disabled(monkeypatch):
    monkeypatch.setattr(
        "backend.skills.registry._load_skills_config",
        lambda: (
            {
                "skills": {
                    "web-search": {"enabled": False, "actions": {"search": True, "answer_with_sources": True}}
                }
            },
            None,
        ),
    )

    result = execute_skill("web-search", action_name="search", query="联网查一下现在的新闻")

    assert result.success is False
    assert result.skill_name == "web-search"
    assert "已禁用" in result.errors[0]
