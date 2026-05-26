"""通用 Agent 对话提示词。"""

from __future__ import annotations

import hashlib
import json


def _compact_text(value: object, limit: int = 420) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 16)] + "……[已截断]"


def _format_recent_messages(recent_messages: list[dict] | None, limit: int = 8) -> str:
    items = []
    for item in (recent_messages or [])[-limit:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip() or "user"
        content = _compact_text(item.get("content") or "", 260)
        if not content:
            continue
        if role == "assistant":
            label = "助手"
        elif role == "system":
            label = "系统"
        elif role == "tool":
            label = "工具"
        else:
            label = "用户"
        items.append(f"{label}：{content}")
    return "\n".join(items)


def _format_compact_json(value: object, limit: int = 1800) -> str:
    if value in (None, "", [], {}):
        return ""
    try:
        text = json.dumps(value, ensure_ascii=False, default=str, indent=2)
    except Exception:
        text = str(value)
    return _compact_text(text, limit)


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    """检查文本是否命中任意关键词。"""
    return any(keyword in text for keyword in keywords)


def detect_general_chat_intent(message: str) -> str:
    """识别普通聊天的细分意图。"""
    text = (message or "").strip()
    lowered = text.lower()
    if not text:
        return "smalltalk"

    if _contains_any(text, ("你好", "您好", "嗨", "早上好", "下午好", "晚上好", "在吗", "在不在")):
        return "smalltalk"
    if _contains_any(text, ("谢谢", "感谢", "多谢", "辛苦了", "谢谢你", "thx")):
        return "gratitude"
    if _contains_any(text, ("有点累", "好累", "累了", "心累", "压力大", "有点烦", "有点疲惫")):
        return "comfort"
    if _contains_any(text, ("你是谁", "你是什么", "介绍一下你自己", "自我介绍", "你是哪个助手")):
        return "capability_intro"
    if _contains_any(text, ("你能做什么", "有什么功能", "你会什么", "可以帮我做什么", "你现在能帮我分析什么")):
        return "capability_intro"
    if _contains_any(text, ("你和普通大模型有什么区别", "普通大模型", "和普通模型有什么区别", "是不是只能回答拉曼问题", "只能回答拉曼问题", "只能回答 Raman 问题")):
        return "capability_intro"
    if _contains_any(text, ("今天天气", "天气怎么样", "天气如何", "天气", "气温", "下雨", "晴天")):
        return "weather"
    if _contains_any(text, ("讲个笑话", "说个笑话", "来个笑话", "逗我笑", "冷笑话", "段子")):
        return "joke"
    return "general_chat"


def _pick_variant(message: str, variants: tuple[str, ...]) -> str:
    """按消息内容稳定选取一个回复变体，避免总是同一句。"""
    if not variants:
        return ""
    digest = hashlib.sha1((message or "").encode("utf-8")).hexdigest()
    index = int(digest[:8], 16) % len(variants)
    return variants[index]


def build_general_chat_local_reply(message: str, system_context: dict | None = None, intent: str | None = None) -> str:
    """构造不依赖 LLM 的普通对话回复。"""
    context = system_context or {}
    current_model = context.get("current_model_version")
    resolved_intent = intent or detect_general_chat_intent(message)

    if resolved_intent == "smalltalk":
        return _pick_variant(
            message,
            (
                "你好，我是当前工作台里的多功能 Agent。你可以直接聊天，也可以上传文件让我调用对应 Skill 处理。",
                "你好，我在。你可以先随便聊两句，也可以直接让我帮你看模型、历史记录、文件或 Raman 光谱。",
                "你好，我是这个工作台的通用 Agent。今天如果想轻松聊聊或者直接做点分析，都可以。",
            ),
        )

    if resolved_intent == "gratitude":
        return _pick_variant(
            message,
            (
                "不客气，我在这儿。你如果还想继续看模型、历史记录、文件处理或 Raman 分析，直接告诉我就行。",
                "不客气，能帮上忙就好。接下来如果要分析文件、检查模型文件或调用某个 Skill，我也可以继续跟上。",
                "不客气，随时叫我。你要是想继续聊业务问题、文件处理或者 Raman 分析，我都可以接着来。",
            ),
        )

    if resolved_intent == "comfort":
        return _pick_variant(
            message,
            (
                "听起来你今天有点累了，先缓一缓也没关系。要是你想换个轻松点的话题，或者直接把文件处理任务交给我，我都在。",
                "辛苦了，先别急着硬扛。你可以先休息一下，也可以把任务交给我，比如查模型、看历史记录、处理文件或分析 Raman CSV。",
                "如果今天状态不太好，先慢一点也可以。你要是愿意，我可以先陪你聊两句，或者直接接手一些分析工作。",
            ),
        )

    if resolved_intent == "capability_intro":
        return _pick_variant(
            message,
            (
                f"我是一个多功能 Agent。当前内置了系统查询、通用文件处理和 Raman 光谱处理等 Skill。普通问题我也能简洁回答；如果你愿意，我也可以继续帮你看模型或分析文件。{f'当前模型版本是 {current_model}。' if current_model else ''}",
                f"我是这个工作台的通用 Agent。专业一点说，我可以按 Skill 分工处理文件、Raman 光谱、报告和系统状态；日常聊天也可以。{f'当前模型版本是 {current_model}。' if current_model else ''}",
                f"我是多功能 Agent，不只是能回答 Raman 问题，也能做基础聊天、模型查看和通用文件分析。{f'当前系统记录的模型版本是 {current_model}。' if current_model else ''}",
            ),
        )

    if resolved_intent == "weather":
        return _pick_variant(
            message,
            (
                "我这边看不到实时天气，不过可以陪你简单聊聊；如果你要的话，我也可以继续帮你看模型、历史记录或者文件。",
                "实时天气我没法直接查询，但我可以先陪你聊两句。要是你想做文件分析或 Raman 分析，也可以直接发我文件。",
                "天气这类实时信息我不敢乱猜，不过我可以继续帮你做更擅长的事，比如查模型、看历史记录、处理文件。",
            ),
        )

    if resolved_intent == "joke":
        return _pick_variant(
            message,
            (
                "来一个轻松版：最稳定的不是报表格式，而是大家碰到异常时先怀疑自己。要不要我顺手再来一个？",
                "可以，来个短的：做分析最怕的不是峰太少，而是把“看起来很像”误当成“真的一样”。如果你愿意，我还能继续陪你聊点别的。",
                "来一个简短的：我最擅长的不是抖包袱，是把任务拆清楚。不过轻松一下也没问题。",
            ),
        )

    if current_model:
        return f"我是这个工作台的多功能 Agent。当前系统记录的模型版本是 {current_model}。如果你要，我可以继续帮你聊基础问题，也可以直接看模型、历史记录、处理文件或分析 Raman CSV。"
    return "我是这个工作台的多功能 Agent。除了 Raman 光谱处理，我也能做基础聊天、系统查询和通用文件分析。"


def build_general_chat_system_prompt(system_context: dict | None = None) -> str:
    """构造通用 Agent 的系统提示词。"""
    context = system_context or {}
    current_model = context.get("current_model_version", "当前未提供")
    llm_provider_info = context.get("llm_provider_info", {}) or {}
    provider_name = llm_provider_info.get("provider_name", "当前未提供")
    provider_base_url = llm_provider_info.get("base_url", "当前未提供")
    provider_model = llm_provider_info.get("model", "当前未提供")
    summary = _compact_text(context.get("summary") or "", 1000)
    recent_messages = _format_recent_messages(context.get("recent_messages") or [], limit=8)
    last_analysis = _format_compact_json(context.get("last_analysis"), limit=2000)
    task_state = _format_compact_json(context.get("task_state"), limit=1800)
    session_id = _compact_text(context.get("session_id") or "", 120)

    memory_sections = []
    if session_id:
        memory_sections.append(f"会话 ID：{session_id}")
    if summary:
        memory_sections.append(f"会话摘要：{summary}")
    if recent_messages:
        memory_sections.append("最近对话：\n" + recent_messages)
    if last_analysis:
        memory_sections.append("最近分析：\n" + last_analysis)
    if task_state:
        memory_sections.append("任务状态：\n" + task_state)

    memory_block = "\n\n".join(memory_sections)
    return (
        "你是一个多功能 Agent，运行在一个基于 Skill 的工作台里。"
        "你既可以进行普通对话，也可以帮助用户处理文件、理解项目结构、查看系统状态，以及在需要时调用 Raman 光谱处理能力。"
        "默认用中文回答，语气自然、清晰、友好，像一个靠谱的科研工程助手。"
        "对于寒暄、感谢、能力范围、轻松闲聊等普通问题，请用 1 到 3 句自然回应，不要套固定模板。"
        "如果用户表现出疲惫、烦躁或压力大，请给出简短、友好的安慰，然后再提供继续帮助的选项。"
        "你可以回答通用问题，但不要编造不存在的工具、文件、分析结果或系统状态。"
        "用户问 Raman、光谱、机器学习、项目开发时，可以做专业解释。"
        "不要编造当前模型版本、历史记录、实验结果、文件分析结果。"
        "涉及真实系统状态时，应提醒用户使用或调用对应工具。"
        "如果用户要分析文件，应提示使用上传入口；如果是 Raman CSV，可说明会进入 Raman 光谱处理 Skill。"
        "如果用户问“我是谁”，说明当前没有登录用户系统，不能确定身份。"
        "不要过度承诺实验结论，不要说预测结果绝对准确。"
        "光谱质量分析只能作为辅助判断，需要结合实验条件和人工复核。"
        f"当前系统上下文中可知的模型版本参考：{current_model}。"
        f"当前系统上下文中可知的通用大模型平台参考：{provider_name}，接口地址参考：{provider_base_url}，模型参考：{provider_model}。"
        "如果提供了会话记忆，请把它视为当前会话的真实上下文，优先用于指代消解和连续追问。"
        "如果用户问“刚才”“继续”“下一步”“现在做到哪一步了”“生成刚才的报告”“和历史样品比一下”等问题，请结合最近对话、最近分析和任务状态来回答，不要重新猜测。"
        + (f"\n\n【当前会话记忆】\n{memory_block}" if memory_block else "")
        + "如果某项数据当前未提供，就明确说“当前未提供”，不要脑补。"
    )
