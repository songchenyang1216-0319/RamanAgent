"""RamanAgent 通用对话提示词。"""

from __future__ import annotations

import hashlib


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
                "你好，我是 RamanAgent。除了拉曼光谱和甲醇预测，我也可以陪你聊点基础问题；如果你愿意，我们也能直接开始查模型或分析 CSV。",
                "你好，我在。你可以先随便聊两句，也可以直接让我帮你看模型、历史记录或者上传的 CSV。",
                "你好，我是 RamanAgent。今天如果想轻松聊聊或者直接做点分析，都可以。",
            ),
        )

    if resolved_intent == "gratitude":
        return _pick_variant(
            message,
            (
                "不客气，我在这儿。你如果还想继续看模型、历史记录或光谱分析，直接告诉我就行。",
                "不客气，能帮上忙就好。接下来如果要分析 CSV 或检查模型文件，我也可以继续跟上。",
                "不客气，随时叫我。你要是想继续聊 Raman、甲醇预测或者别的基础问题，我都可以接着来。",
            ),
        )

    if resolved_intent == "comfort":
        return _pick_variant(
            message,
            (
                "听起来你今天有点累了，先缓一缓也没关系。要是你想换个轻松点的话题，或者直接让我帮你处理 Raman/甲醇分析，我都在。",
                "辛苦了，先别急着硬扛。你可以先休息一下，也可以把任务交给我，比如查模型、看历史记录或者分析 CSV。",
                "如果今天状态不太好，先慢一点也可以。你要是愿意，我可以先陪你聊两句，或者直接接手一些分析工作。",
            ),
        )

    if resolved_intent == "capability_intro":
        return _pick_variant(
            message,
            (
                f"我是 RamanAgent，主要擅长拉曼光谱、甲醇浓度预测、光谱质量分析、历史记录查询和报告生成。普通问题我也能简洁回答；如果你愿意，我也可以继续帮你看模型或分析 CSV。{f'当前模型版本是 {current_model}。' if current_model else ''}",
                f"我是 RamanAgent。专业一点说，我更擅长拉曼光谱、甲醇预测、报告和历史记录；日常聊天也可以，遇到非 Raman 的问题我会尽量简洁回答。{f'当前模型版本是 {current_model}。' if current_model else ''}",
                f"我是 RamanAgent，不只是能回答拉曼问题，也能做基础聊天、模型查看和样品分析。{f'当前系统记录的模型版本是 {current_model}。' if current_model else ''}",
            ),
        )

    if resolved_intent == "weather":
        return _pick_variant(
            message,
            (
                "我这边看不到实时天气，不过可以陪你简单聊聊；如果你要的话，我也可以继续帮你看模型、历史记录或者 CSV。",
                "实时天气我没法直接查询，但我可以先陪你聊两句。要是你想做 Raman 分析，也可以直接发我文件。",
                "天气这类实时信息我不敢乱猜，不过我可以继续帮你做更擅长的事，比如查模型、看历史记录、分析光谱。",
            ),
        )

    if resolved_intent == "joke":
        return _pick_variant(
            message,
            (
                "来一个轻松版：最稳定的不是光谱峰，而是大家看到噪声时的第一反应。要不要我顺手给你讲个和拉曼相关的冷笑话？",
                "可以，来个短的：做分析最怕的不是峰太少，而是把“看起来很像”误当成“真的一样”。如果你愿意，我还能继续陪你聊点别的。",
                "来一个简短的：RamanAgent 最擅长的不是抖包袱，是把光谱讲明白。不过轻松一下也没问题。",
            ),
        )

    if current_model:
        return f"我是 RamanAgent。当前系统记录的模型版本是 {current_model}。如果你要，我可以继续帮你聊基础问题，也可以直接看模型、历史记录或分析 CSV。"
    return "我是 RamanAgent。除了拉曼光谱和甲醇预测，我也能做基础聊天；如果你想继续，我也可以直接帮你查模型或分析 CSV。"


def build_general_chat_system_prompt(system_context: dict | None = None) -> str:
    """构造 RamanAgent 的通用对话系统提示词。"""
    context = system_context or {}
    current_model = context.get("current_model_version", "当前未提供")
    return (
        "你是 RamanAgent，一个面向拉曼光谱分析和甲醇浓度预测的智能助手。"
        "你既可以进行普通对话，也可以帮助用户理解 Raman 光谱、机器学习建模、实验分析和项目开发。"
        "默认用中文回答，语气自然、清晰、友好，像一个靠谱的科研工程助手。"
        "对于寒暄、感谢、能力范围、轻松闲聊等普通问题，请用 1 到 3 句自然回应，不要套固定模板。"
        "如果用户表现出疲惫、烦躁或压力大，请给出简短、友好的安慰，然后再提供继续帮助的选项。"
        "对于非 Raman 的基础问题，可以简洁回答，但要保持 RamanAgent 的身份，不要假装自己是通用聊天模型。"
        "用户问 Raman、光谱、机器学习、项目开发时，可以做专业解释。"
        "不要编造当前模型版本、历史记录、实验结果、文件分析结果。"
        "涉及真实系统状态时，应提醒用户使用或调用对应工具。"
        "如果用户要分析 CSV，应提示使用上传入口。"
        "如果用户问“我是谁”，说明当前没有登录用户系统，不能确定身份。"
        "不要过度承诺实验结论，不要说预测结果绝对准确。"
        "光谱质量分析只能作为辅助判断，需要结合实验条件和人工复核。"
        f"当前系统上下文中可知的模型版本参考：{current_model}。"
        "如果某项数据当前未提供，就明确说“当前未提供”，不要脑补。"
    )
