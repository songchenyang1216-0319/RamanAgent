"""通用 Agent 意图分类提示词。"""

from __future__ import annotations

import json


ALLOWED_LLM_INTENTS = (
    "general_chat",
    "raman_qa",
    "model_info",
    "system_info_query",
    "history_query",
    "file_analysis",
    "report_generation",
    "spectral_quality",
    "peak_analysis",
    "compare_history",
    "unknown",
)


def build_intent_classifier_system_prompt() -> str:
    """构造只输出 JSON 的意图分类系统提示词。"""
    intents_text = ", ".join(ALLOWED_LLM_INTENTS)
    return (
        "你是一个通用多功能 Agent 的意图分类器。"
        "你的任务不是回答用户问题，而是把用户消息分类成一个结构化 JSON。"
        "你必须只输出 JSON，不要输出 Markdown，不要输出解释性前缀，不要输出代码块。"
        "不要编造文件路径、模型结果、历史记录或系统状态。"
        "如果意图不明确，优先返回 unknown 或 general_chat。"
        "可用意图只有这些："
        f"{intents_text}。"
        "其中：model_info 表示询问当前模型、模型文件、当前权重或系统正在使用的模型能力；"
        "system_info_query 表示询问系统状态、平台来源、Skills 状态、会话信息、模型列表或运行配置；"
        "history_query 表示查看历史记录、最近一次实验、过去结果；"
        "file_analysis 表示想分析上传文件或样品；"
        "report_generation 表示要生成报告或导出总结；"
        "spectral_quality 表示评估谱图质量、噪声、基线或采集质量；"
        "peak_analysis 表示峰识别、峰解释或问某个峰对应什么；"
        "compare_history 表示要和历史样品、之前样品或过去结果做对比；"
        "raman_qa 表示 Raman、光谱、模型等领域知识问答；"
        "general_chat 表示普通闲聊、寒暄、泛化闲谈。"
        "如果 intent 是 model_info 或 system_info_query，请尽量在 slots.system_info_target 里填写最接近的目标，"
        "可选值包括 provider、current_model、model_artifacts、model_versions、skills、session、overview。"
    )


def build_intent_classifier_user_prompt(message: str) -> str:
    """构造用户提示词。"""
    payload = {
        "instruction": "请只输出 JSON。",
        "output_schema": {
            "intent": "必须是允许的意图之一",
            "confidence": "0 到 1 之间的小数",
            "reason": "简短中文原因",
            "slots": {},
        },
        "user_message": message,
    }
    return json.dumps(payload, ensure_ascii=False)
