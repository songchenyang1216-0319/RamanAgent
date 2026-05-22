from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.agent.agent_service import RamanAgentService


def test_builtin_and_tool_intents():
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


def test_general_chat_and_fallback():
    service = RamanAgentService()

    greeting = service.chat("你好")
    assert greeting["category"] == "general_chat"
    assert greeting["intent"] == "smalltalk"
    assert greeting["reply"]

    thanks = service.chat("谢谢")
    assert thanks["category"] == "general_chat"
    assert thanks["intent"] == "gratitude"
    assert "不客气" in thanks["reply"] or "随时" in thanks["reply"]

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


def test_general_chat_debug_and_no_large_fields_by_default():
    service = RamanAgentService()

    normal = service.chat("你好")
    assert "available_tools" not in normal
    assert "tool_result" not in normal

    debug = service.chat("你好", debug=True)
    assert debug["debug"] is True
    assert "available_tools" in debug
    assert "raw_intent" in debug
