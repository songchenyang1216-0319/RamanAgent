from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.agent.agent_service import RamanAgentService


def _mock_llm(monkeypatch):
    monkeypatch.setattr(
        "backend.services.llm_service.LLMService._chat_complete",
        lambda self, system_prompt, user_prompt: (f"模拟回复：当前使用 {self.provider}/{self.model}。", {"mock": True}),
    )


def test_builtin_and_tool_intents(monkeypatch):
    _mock_llm(monkeypatch)
    service = RamanAgentService()

    identity = service.chat("你是谁")
    assert identity["intent"] == "capability_intro"
    assert identity["category"] == "general_chat"

    capabilities = service.chat("你能做什么")
    assert capabilities["intent"] == "capability_intro"
    assert capabilities["category"] == "general_chat"

    user_identity = service.chat("我是谁")
    assert user_identity["intent"] == "capability_intro"
    assert user_identity["category"] == "general_chat"

    upload_help = service.chat("怎么上传 CSV")
    assert upload_help["intent"] == "upload_help"
    assert upload_help["category"] == "builtin"

    model = service.chat("当前用的是哪个模型？")
    assert model["category"] == "tool"
    assert model["tool_used"] == "get_current_model"

    check_model = service.chat("模型文件齐全吗？")
    assert check_model["category"] == "tool"
    assert check_model["tool_used"] in {"check_current_model", "check_artifacts"}

    history = service.chat("查看最近实验记录")
    assert history["category"] == "tool"


def test_general_chat_and_fallback(monkeypatch):
    _mock_llm(monkeypatch)
    service = RamanAgentService()

    greeting = service.chat("你好")
    assert greeting["category"] == "general_chat"
    assert greeting["intent"] == "smalltalk"
    assert greeting["reply"]

    thanks = service.chat("谢谢")
    assert thanks["category"] == "general_chat"
    assert thanks["intent"] == "gratitude"
    assert thanks["reply"]

    knowledge = service.chat("拉曼光谱和红外光谱有什么区别")
    assert knowledge["category"] == "general_chat"
    assert knowledge["reply"]

    tired = service.chat("今天有点累")
    assert tired["category"] == "general_chat"
    assert tired["intent"] == "comfort"
    assert tired["reply"]

    weather = service.chat("今天天气怎么样")
    assert weather["category"] == "general_chat"
    assert weather["intent"] == "weather"
    assert weather["reply"]

    joke = service.chat("给我讲个笑话")
    assert joke["category"] == "general_chat"
    assert joke["intent"] == "joke"
    assert joke["reply"]


def test_general_chat_opinion_does_not_trigger_raman(monkeypatch):
    _mock_llm(monkeypatch)
    service = RamanAgentService()

    response = service.chat("你对普京访华的事情有什么看法？")
    assert response["success"] is True
    assert response["intent"] == "general_chat"
    assert response["category"] == "general_chat"
    assert response.get("skill_name") is None


def test_web_search_intent(monkeypatch):
    _mock_llm(monkeypatch)
    service = RamanAgentService()
    monkeypatch.setattr(
        service,
        "run_tool",
        lambda tool_name, params=None: {
            "success": True,
            "query": (params or {}).get("query"),
            "total": 1,
            "items": [{"title": "Agent 项目", "url": "https://example.com", "snippet": "示例结果"}],
            "source": "mock",
            "used_provider": "tavily",
            "answer": "示例搜索答案",
        }
        if tool_name == "web_search"
        else {"success": True, "data": {"model_version": "methanol_v1"}},
    )
    monkeypatch.setattr(
        "backend.services.llm_service.LLMService.generate_skill_augmented_reply",
        lambda self, skill_context, user_message, conversation_context=None: {
            "success": True,
            "reply": "整理后的联网搜索回答",
            "error_message": None,
            "raw_response": {"mock": True},
            "model_info": self.get_current_model_info(),
        },
    )

    response = service.chat("现在 GitHub 上比较火的 Agent 项目有哪些？")
    assert response["success"] is True
    assert response["intent"] == "web_search"
    assert response["category"] == "tool"
    assert response["tool_used"] == "web_search"
    assert response["skill_name"] == "web-search"
    assert response["action_name"] == "search"
    assert response["used_skill"] is True
    assert response["data"]["used_provider"] == "tavily"
    assert response["data"]["items"]


def test_general_chat_debug_and_no_large_fields_by_default(monkeypatch):
    _mock_llm(monkeypatch)
    service = RamanAgentService()

    normal = service.chat("你好")
    assert "available_tools" not in normal
    assert "tool_result" not in normal

    debug = service.chat("你好", debug=True)
    assert debug["debug"] is True
    assert "available_tools" in debug
    assert "raw_intent" in debug
