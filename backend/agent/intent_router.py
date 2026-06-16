"""轻量级规则意图识别器。"""

from __future__ import annotations

import re

from backend.agent.types import IntentResult, NormalizedMessage


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    """检查文本是否命中任意关键词。"""
    return any(keyword in text for keyword in keywords)


def _is_knowledge_question(text: str) -> bool:
    """判断用户是否只是在问知识，而不是要求执行工具。"""
    lowered = str(text or "").lower()
    knowledge_markers = (
        "有哪些",
        "是什么",
        "什么是",
        "区别",
        "原理",
        "为什么",
        "怎么理解",
        "如何理解",
        "介绍",
        "解释一下",
        "讲一下",
        "讲讲",
        "怎么看",
        "看法",
        "有什么看法",
        "怎么学习",
        "怎么学",
        "报告怎么写",
        "一般用什么",
        "适合什么",
        "方法",
    )
    return any(marker in text for marker in knowledge_markers) or any(
        marker in lowered for marker in ("what is", "how to", "why", "difference")
    )


def _has_execution_marker(text: str) -> bool:
    """判断用户是否明确要求基于文件或上下文执行动作。"""
    lowered = str(text or "").lower()
    execution_markers = (
        "这个文件",
        "刚才",
        "它",
        "他",
        "上传",
        "csv",
        "样品",
        "帮我",
        "对这个",
        "把这个",
        "执行",
        "进行",
        "处理",
        "生成刚才",
        "分析这个",
        "继续",
    )
    return any(marker in text for marker in execution_markers) or any(
        marker in lowered for marker in ("this file", "uploaded", "csv", "run", "execute")
    )


def _is_file_context_request(text: str) -> bool:
    lowered = str(text or "").lower()
    markers = (
        "这个文件",
        "它",
        "他",
        "其",
        "刚才那个文件",
        "那个文件",
        "那个csv",
        "那个 csv",
        "上一个文件",
        "当前文件",
        "上传的文件",
        "csv文件",
        "csv 文件",
        "excel文件",
        "excel 文件",
        "主要内容",
        "内容是什么",
        "内容总结",
        "总结这个",
        "总结一下",
        "分析这个",
        "处理这个",
        "转换这个",
        "这个表格",
        "这个文档",
        "这个 pdf",
        "这个pdf",
        "这个 csv",
        "这个csv",
        "文件格式",
        "是什么格式",
        "this file",
        "uploaded file",
        "previous file",
    )
    return any(marker in lowered for marker in markers)


def _is_code_analysis_request(text: str) -> bool:
    lowered = str(text or "").lower()
    markers = (
        "代码",
        "脚本",
        "函数",
        "class",
        "报错",
        "bug",
        "解释这段代码",
        "解释这个代码",
        "详细解释",
        "看下这段代码",
        "帮我看代码",
        "分析代码",
        "code",
        "script",
        "function",
        "traceback",
        "python",
        ".py",
    )
    return any(marker in lowered for marker in markers)


def _is_document_transform_request(text: str) -> bool:
    lowered = str(text or "").lower()
    markers = (
        "总结",
        "摘要",
        "概括",
        "归纳",
        "分析一下",
        "帮我分析",
        "提取重点",
        "重点",
        "要点",
        "大纲",
        "目录",
        "结构",
        "翻译",
        "译成",
        "润色",
        "改写",
        "整理",
        "简介",
        "主要内容",
        "内容是什么",
        "内容总结",
        "读一下",
        "看一下",
        "review",
        "summarize",
        "summary",
        "outline",
        "translate",
        "polish",
    )
    return any(marker in lowered for marker in markers)


def _is_light_file_info_request(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(keyword in lowered for keyword in ("文件格式", "是什么格式", "多大", "文件名", "mime", "metadata", "元数据"))


def _is_knowledge_base_request(text: str) -> bool:
    lowered = str(text or "").lower()
    markers = (
        "知识库",
        "资料库",
        "知识库里",
        "资料库里",
        "项目资料",
        "专业资料",
        "团队资料",
        "kb",
        "knowledge base",
    )
    return any(marker in lowered for marker in markers)


def _is_rag_answer_request(text: str) -> bool:
    lowered = str(text or "").lower()
    if _is_document_transform_request(text) and not any(keyword in lowered for keyword in ("查找", "检索", "引用", "出处", "回答", "有没有", "在哪里")):
        return False
    markers = (
        "根据这个文件",
        "基于这个文件",
        "这个文件里",
        "文件里",
        "文档里",
        "资料里",
        "从这个文件",
        "查找",
        "检索",
        "回答这个问题",
        "问答",
        "依据",
        "引用",
        "出处",
        "有没有",
        "是否提到",
        "在哪里",
        "哪一段",
        "第几页",
        "source",
        "citation",
        "find",
        "search",
        "where",
        "does it mention",
    )
    return any(marker in lowered for marker in markers)


def _is_file_conversion_request(text: str) -> bool:
    lowered = str(text or "").lower()
    markers = ("转换", "转成", "转为", "导出为", "另存为", "convert to", "export as")
    formats = ("pdf", "docx", "word", "md", "markdown", "html", "txt", "csv", "xlsx", "excel")
    return any(marker in lowered for marker in markers) and any(fmt in lowered for fmt in formats)


def _extract_history_id(message: str) -> str | None:
    """优先从文本中提取显式 history_id 或 task_id。"""
    patterns = [
        r"history_id\s*[:=]\s*([0-9A-Za-z_-]+)",
        r"task_id\s*[:=]\s*([0-9A-Za-z_-]+)",
        r"记录\s*ID\s*[:=]?\s*([0-9A-Za-z_-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def _extract_history_index(message: str) -> int | None:
    """从“第 3 条记录”这类文本中提取序号。"""
    match = re.search(r"第\s*(\d+)\s*条", message)
    if not match:
        return None
    try:
        value = int(match.group(1))
    except ValueError:
        return None
    return value if value > 0 else None


def detect_intent(message: str) -> dict:
    """根据关键词规则识别当前意图。"""
    text = (message or "").strip()
    lowered = text.lower()

    if not text:
        return {"intent": "help", "category": "help", "confidence": 1.0, "params": {}}

    if any(keyword in text for keyword in ("模型文件", "模型是否齐全", "检查模型", "模型文件正常吗")) or "artifacts" in lowered:
        return {"intent": "check_artifacts", "category": "tool", "confidence": 0.98, "params": {}}

    if any(keyword in text for keyword in ("当前模型", "模型版本", "用的是哪个模型", "当前用的模型是什么", "背后跑的是什么模型", "跑的是什么模型")):
        return {"intent": "get_current_model", "category": "tool", "confidence": 0.98, "params": {}}

    if any(
        keyword in text
        for keyword in (
            "哪个平台的大模型",
            "大模型平台",
            "模型平台",
            "平台的大模型",
            "硅基流动",
            "siliconflow",
            "是不是硅基流动",
            "还是其他平台",
            "你现在用的是什么平台",
            "你用的是哪个平台",
            "大模型是哪里的",
            "大模型来源",
            "供应商",
            "provider",
        )
    ):
        return {"intent": "system_info_query", "category": "tool", "confidence": 0.98, "params": {"query_type": "provider"}}

    if any(keyword in text for keyword in ("所有模型", "有哪些模型版本", "列出模型版本", "模型列表")):
        return {"intent": "list_model_versions", "category": "tool", "confidence": 0.96, "params": {}}

    if any(keyword in text for keyword in ("检查当前模型", "模型文件齐全吗", "模型能不能用")):
        return {"intent": "check_current_model", "category": "tool", "confidence": 0.98, "params": {}}

    if any(keyword in text for keyword in ("skills 状态", "skill 状态", "技能状态", "当前 skills", "当前 skills 状态", "有哪些 skills", "skill 列表", "技能列表")):
        return {"intent": "system_info_query", "category": "tool", "confidence": 0.96, "params": {"query_type": "skills"}}

    if any(keyword in text for keyword in ("会话 id", "session id", "当前会话", "会话状态", "当前 session")):
        return {"intent": "system_info_query", "category": "tool", "confidence": 0.94, "params": {"query_type": "session"}}

    if any(keyword in text for keyword in ("实验详情", "样品详情")):
        history_id = _extract_history_id(text)
        history_index = _extract_history_index(text)
        return {
            "intent": "get_experiment_detail",
            "category": "tool",
            "confidence": 0.94,
            "params": {"history_id": history_id, "history_index": history_index},
        }

    has_detail = any(keyword in text for keyword in ("详情", "记录详情", "查看第")) or "history_id" in lowered or "task_id" in lowered
    if has_detail:
        history_id = _extract_history_id(text)
        history_index = _extract_history_index(text)
        return {
            "intent": "get_history_detail",
            "category": "tool",
            "confidence": 0.94,
            "params": {"history_id": history_id, "history_index": history_index},
        }

    if any(keyword in text for keyword in ("实验记录", "样品记录", "最近实验", "分析历史", "最近一次实验结果", "最近一次预测结果")):
        return {"intent": "get_experiment_history", "category": "tool", "confidence": 0.95, "params": {"limit": 10}}

    if _contains_any(text, ("你好", "您好", "嗨", "早上好", "下午好", "晚上好", "在吗", "在不在")):
        return {"intent": "smalltalk", "category": "general_chat", "confidence": 0.99, "params": {}}

    if _contains_any(text, ("谢谢", "感谢", "多谢", "辛苦了", "谢谢你", "thx")):
        return {"intent": "gratitude", "category": "general_chat", "confidence": 0.99, "params": {}}

    if _contains_any(text, ("有点累", "好累", "累了", "心累", "压力大", "有点烦", "有点疲惫")):
        return {"intent": "comfort", "category": "general_chat", "confidence": 0.97, "params": {}}

    if _contains_any(text, ("你是谁", "你是什么", "介绍一下你自己", "自我介绍", "你是哪个助手", "ramanagent 是什么")):
        return {"intent": "capability_intro", "category": "general_chat", "confidence": 0.99, "params": {}}

    if _contains_any(text, ("你能做什么", "有什么功能", "你会什么", "可以帮我做什么", "你现在能帮我分析什么")):
        return {"intent": "capability_intro", "category": "general_chat", "confidence": 0.99, "params": {}}

    if _contains_any(text, ("你和普通大模型有什么区别", "普通大模型", "和普通模型有什么区别", "是不是只能回答拉曼问题", "只能回答拉曼问题", "只能回答 Raman 问题")):
        return {"intent": "capability_intro", "category": "general_chat", "confidence": 0.98, "params": {}}

    if _contains_any(text, ("今天天气", "天气怎么样", "天气如何", "天气", "气温", "下雨", "晴天")):
        return {"intent": "weather", "category": "general_chat", "confidence": 0.96, "params": {}}

    if _contains_any(text, ("讲个笑话", "说个笑话", "来个笑话", "逗我笑", "冷笑话", "段子")):
        return {"intent": "joke", "category": "general_chat", "confidence": 0.96, "params": {}}

    if _contains_any(text, ("随便聊聊", "随便说说", "聊聊天", "先聊聊", "简单聊聊")):
        return {"intent": "general_chat", "category": "general_chat", "confidence": 0.96, "params": {}}

    github_current_query = "github" in lowered and any(keyword in text for keyword in ("现在", "最新", "比较火", "热门", "项目"))
    explicit_web_search = any(
        keyword in text
        for keyword in (
            "搜索一下",
            "搜索",
            "查一下",
            "查一查",
            "找一下",
            "网上搜索",
            "网上查",
            "联网搜索",
            "联网查一下",
            "联网查",
            "今天",
            "今年",
            "最新",
            "最近",
            "新闻",
            "近况",
            "最近消息",
            "相关内容",
            "价格",
            "当前版本",
        )
    )
    if github_current_query or explicit_web_search:
        return {"intent": "web_search", "category": "tool", "confidence": 0.92, "params": {"query": text, "limit": 5}}

    if _contains_any(text, ("多少次", "来过多少次", "访问过几次", "一共来过", "来了几次")) and not _has_execution_marker(text):
        return {"intent": "web_search", "category": "tool", "confidence": 0.9, "params": {"query": text, "limit": 5}}

    if any(keyword in text for keyword in ("历史记录", "最近分析", "上一次", "之前的结果", "分析记录", "上一次预测浓度")):
        return {"intent": "list_history", "category": "tool", "confidence": 0.95, "params": {"limit": 10}}

    if _is_knowledge_question(text) and not _has_execution_marker(text):
        return {"intent": "general_chat", "category": "general_chat", "confidence": 0.86, "params": {"reason": "knowledge_question"}}

    if any(keyword in text for keyword in ("专业分析", "综合分析", "帮我看看这个光谱", "这个样品靠谱吗", "这个结果可信吗")):
        return {"intent": "professional_spectral_analysis", "category": "tool", "confidence": 0.9, "params": {}}

    if any(keyword in text for keyword in ("光谱质量", "信噪比", "噪声", "质量怎么样", "采集质量")):
        return {"intent": "analyze_spectrum_quality", "category": "tool", "confidence": 0.92, "params": {}}

    if any(keyword in text for keyword in ("基线", "去基线")) or "baseline" in lowered or "als" in lowered or "cae+" in lowered:
        return {"intent": "analyze_baseline_quality", "category": "tool", "confidence": 0.92, "params": {}}

    if any(keyword in text for keyword in ("特征峰", "峰位")) or "峰" in text or "peak" in lowered or "raman peak" in lowered:
        return {"intent": "detect_peaks", "category": "tool", "confidence": 0.92, "params": {}}

    if any(keyword in text for keyword in ("分析样品", "预测甲醇", "分析这个csv", "分析这个CSV", "测这个文件", "拉曼样品分析", "帮我分析这个csv", "帮我分析这个CSV", "帮我分析这个样品")):
        return {"intent": "predict_methanol", "category": "tool", "confidence": 0.95, "params": {}}

    if _contains_any(text, ("我是谁", "你知道我是谁吗", "当前用户是谁")):
        return {"intent": "capability_intro", "category": "general_chat", "confidence": 0.98, "params": {}}

    if any(keyword in text for keyword in ("怎么上传", "怎么分析文件", "csv 怎么传", "CSV 怎么传", "如何开始使用", "怎么用")):
        return {"intent": "upload_help", "category": "builtin", "confidence": 0.95, "params": {}}

    return {"intent": "general_chat", "category": "general_chat", "confidence": 0.6, "params": {}}


class IntentRouter:
    """新编排层使用的意图路由器。"""

    def route(self, normalized_message: NormalizedMessage) -> IntentResult:
        message = str(normalized_message.message or "").strip()
        lowered = message.lower()
        file_type = str(normalized_message.file_type or "").strip().lower()
        file_context_request = _is_file_context_request(message)
        kb_request = _is_knowledge_base_request(message) or bool(normalized_message.knowledge_base_ids)

        if kb_request and normalized_message.has_file:
            return IntentResult(
                intent="mixed_rag",
                confidence=0.93,
                reason="用户明确要求结合当前文件与知识库资料",
                recommended_route="rag",
                requires_file=True,
                requires_llm=True,
            )

        if kb_request:
            return IntentResult(
                intent="knowledge_base_rag",
                confidence=0.92,
                reason="用户明确要求查询知识库资料",
                recommended_route="rag",
                requires_llm=True,
            )

        if self._is_skill_management(message, lowered):
            return IntentResult(
                intent="skill_management",
                confidence=0.98,
                reason="命中 Skill 管理关键词",
                recommended_route="fallback",
            )

        if self._is_model_management(message, lowered):
            return IntentResult(
                intent="model_management",
                confidence=0.98,
                reason="命中模型管理关键词",
                recommended_route="fallback",
            )

        if self._is_web_search(message, lowered):
            return IntentResult(
                intent="web_search",
                confidence=0.92,
                reason="用户明确要求联网或查询最新信息",
                recommended_route="skill",
                candidate_skills=["web-search"],
                requires_tool=True,
                requires_llm=True,
            )

        if any(keyword in lowered for keyword in ("生成报告", "markdown 报告", "markdown报告", "导出报告", "可下载报告")):
            return IntentResult(
                intent="report_generation",
                confidence=0.93,
                reason="用户明确要求生成报告产物",
                recommended_route="skill",
                candidate_skills=["report-generator"],
                requires_llm=True,
            )

        if _is_file_conversion_request(message):
            return IntentResult(
                intent="file_conversion",
                confidence=0.92,
                reason="用户明确要求进行文件格式转换",
                recommended_route="skill",
                candidate_skills=["file-converter"],
                requires_file=True,
                requires_tool=True,
            )

        if normalized_message.has_file:
            if file_type == "code" and (_is_code_analysis_request(message) or file_context_request):
                return IntentResult(
                    intent="code_analysis",
                    confidence=0.97,
                    reason="上传文件被识别为代码，且用户要求解释/分析代码",
                    recommended_route="skill",
                    candidate_skills=["code-assistant"],
                    requires_file=True,
                    requires_llm=True,
                )
            if _is_knowledge_question(message) and not file_context_request and message != "请分析这个文件":
                return IntentResult(
                    intent="general_chat",
                    confidence=0.82,
                    reason="虽然存在附件，但用户问题是普通知识问答，未要求处理文件",
                    recommended_route="model",
                    requires_llm=True,
                )
            if _is_light_file_info_request(message):
                return IntentResult(
                    intent="file_info",
                    confidence=0.95,
                    reason="用户只询问文件轻量元数据",
                    recommended_route="tool",
                    requires_file=True,
                    requires_tool=True,
                )
            if file_type == "raman":
                return IntentResult(
                    intent="raman_analysis",
                    confidence=0.98,
                    reason="上传文件被识别为 Raman/光谱数据",
                    recommended_route="skill",
                    candidate_skills=["raman_spectroscopy_skill"],
                    requires_file=True,
                )
            if file_type == "table":
                return IntentResult(
                    intent="csv_analysis",
                    confidence=0.97,
                    reason="上传文件被识别为 CSV/Excel 表格",
                    recommended_route="tool",
                    candidate_skills=["table-analysis"],
                    requires_file=True,
                    requires_tool=True,
                )
            if file_type == "document":
                if _is_document_transform_request(message) or not _is_rag_answer_request(message):
                    return IntentResult(
                        intent="document_processing",
                        confidence=0.97,
                        reason="上传文件被识别为文档，用户要求摘要/分析/整理等文档处理动作",
                        recommended_route="skill",
                        requires_file=True,
                        requires_llm=True,
                    )
                if _is_rag_answer_request(message):
                    return IntentResult(
                        intent="conversation_rag",
                        confidence=0.94,
                        reason="用户明确要求从当前会话文件中查找依据并回答具体问题",
                        recommended_route="rag",
                        requires_file=True,
                        requires_llm=True,
                    )
            if file_type == "code":
                return IntentResult(
                    intent="document_processing",
                    confidence=0.72,
                    reason="上传文件被识别为代码，但用户未明确说明目标，先按文本文件处理",
                    recommended_route="skill",
                    requires_file=True,
                    requires_llm=True,
                )
            if file_type == "image":
                return IntentResult(
                    intent="image_understanding",
                    confidence=0.88,
                    reason="上传文件被识别为图片，优先交给 Skill 路由",
                    recommended_route="skill",
                    candidate_skills=["image-understanding"],
                    requires_file=True,
                )

            if file_context_request and file_type in {"file", "code", ""}:
                if _is_document_transform_request(message):
                    return IntentResult(
                        intent="document_processing",
                        confidence=0.78,
                        reason="用户要求处理当前文件，但文件类型不明确，先尝试文档处理器而不是检索",
                        recommended_route="skill",
                        requires_file=True,
                        requires_llm=True,
                    )
                return IntentResult(
                    intent="conversation_rag",
                    confidence=0.86,
                    reason="用户要求基于当前文件查找/问答，走会话文件 RAG",
                    recommended_route="rag",
                    requires_file=True,
                    requires_llm=True,
                )

        if any(keyword in lowered for keyword in ("raman", "sers", "光谱", "峰位", "基线校正", "sg 平滑", "sg平滑", "去噪", "浓度预测")):
            return IntentResult(
                intent="raman_analysis",
                confidence=0.9,
                reason="命中 Raman/光谱知识关键词",
                recommended_route="model",
                candidate_skills=["raman_spectroscopy_skill"],
                requires_llm=True,
            )

        if any(keyword in lowered for keyword in ("csv", "excel", "表格", "缺失值", "异常值", "分组", "可视化", "列名", "基本统计")):
            return IntentResult(
                intent="csv_analysis",
                confidence=0.88,
                reason="命中表格分析关键词",
                recommended_route="tool",
                candidate_skills=["table-analysis"],
                requires_tool=True,
            )

        if _is_code_analysis_request(message):
            return IntentResult(
                intent="code_analysis",
                confidence=0.9,
                reason="命中代码解释/分析关键词",
                recommended_route="skill",
                candidate_skills=["code-assistant"],
                requires_llm=True,
            )

        if any(keyword in lowered for keyword in ("翻译", "总结", "润色", "原文对照", "讲稿", "论文", "阅读理解", "整理")):
            return IntentResult(
                intent="document_processing",
                confidence=0.86,
                reason="命中文档处理关键词",
                recommended_route="skill",
                requires_llm=True,
            )

        if any(keyword in lowered for keyword in ("你好", "您好", "你是谁", "帮我解释", "agent 是什么", "agent是什么", "能做什么", "谢谢")):
            return IntentResult(
                intent="general_chat",
                confidence=0.95,
                reason="命中普通聊天/介绍类问法",
                recommended_route="model",
                requires_llm=True,
            )

        legacy = detect_intent(message)
        if str(legacy.get("category") or "") == "general_chat":
            return IntentResult(
                intent="general_chat",
                confidence=float(legacy.get("confidence") or 0.6),
                reason=f"沿用旧规则意图：{legacy.get('intent')}",
                recommended_route="model",
                requires_llm=True,
            )
        return IntentResult(
            intent="unknown",
            confidence=0.35,
            reason=f"低置信度，旧规则识别为 {legacy.get('intent')}",
            recommended_route="fallback",
        )

    def _is_web_search(self, message: str, lowered: str) -> bool:
        return any(
            keyword in message
            for keyword in ("联网", "搜索一下", "查一下", "查资料", "最新", "最近", "找论文", "查政策", "查价格")
        ) or any(keyword in lowered for keyword in ("web search", "latest", "news", "paper"))

    def _is_skill_management(self, message: str, lowered: str) -> bool:
        return any(keyword in message for keyword in ("上传 Skill", "启用 Skill", "禁用 Skill", "刷新 Skill", "Skill 列表", "技能列表")) or "skill" in lowered and any(
            keyword in lowered for keyword in ("upload", "enable", "disable", "list", "refresh")
        )

    def _is_model_management(self, message: str, lowered: str) -> bool:
        return any(keyword in message for keyword in ("切换模型", "模型列表", "当前模型", "查看模型列表", "测试模型连通性")) or "model" in lowered and any(
            keyword in lowered for keyword in ("switch", "list", "current", "connect")
        )
