"""大模型解释服务。"""

from __future__ import annotations

import logging
import os
from typing import Any

from backend.agent.prompts.general_chat_prompt import (
    build_general_chat_local_reply,
    build_general_chat_system_prompt,
)
from backend.core.model_router import ModelRouter
from dotenv import load_dotenv
from raman_core.methanol.config import PROJECT_ROOT


load_dotenv(PROJECT_ROOT / ".env")
logger = logging.getLogger(__name__)
FALLBACK_PREFIX = "当前大模型服务不可用，以下是本地规则生成的简要回答。\n\n"


class LLMService:
    """基于当前选中的大语言模型生成回答与解释。"""

    def __init__(
        self,
        *,
        provider_id: str | None = None,
        model_id: str | None = None,
        user_id: str | None = None,
        conversation_id: str | None = None,
    ):
        def _safe_float(env_name: str, default: float) -> float:
            try:
                return float(os.getenv(env_name, str(default)))
            except (TypeError, ValueError):
                return default

        def _safe_int(env_name: str, default: int) -> int:
            try:
                return int(os.getenv(env_name, str(default)))
            except (TypeError, ValueError):
                return default

        self.model_router = ModelRouter()
        self.selection = self.model_router.get_selected_model(user_id=user_id, conversation_id=conversation_id)
        if provider_id or model_id:
            self.selection = self.model_router.resolve_selection(
                provider_id=provider_id,
                model_id=model_id,
                user_id=user_id,
                conversation_id=conversation_id,
            )
        self.provider_config = dict(self.selection.get("provider_config") or {})
        self.provider = str(self.selection.get("provider_id") or "").strip()
        self.provider_display_name = str(self.selection.get("provider_name") or "").strip()
        self.model = str(self.selection.get("model_id") or "").strip()
        self.model_display_name = str(self.selection.get("model_name") or self.model).strip()
        self.display_name = f"{self.provider_display_name} · {self.model_display_name}".strip(" ·")
        self.supports_vision = bool(self.selection.get("supports_vision"))
        self.api_key_env = str(self.provider_config.get("api_key_env") or "").strip()
        self.base_url = str(self.provider_config.get("base_url") or "").strip()
        self.api_key = str(self.provider_config.get("api_key") or "").strip()
        self.temperature = _safe_float("LLM_TEMPERATURE", 0.6)
        self.max_tokens = _safe_int("LLM_MAX_TOKENS", 4096)
        self.timeout_seconds = _safe_int("LLM_TIMEOUT_SECONDS", 60)
        self.default_stream = str(os.getenv("LLM_STREAM", "true")).strip().lower() in {"1", "true", "yes", "on"}
        self.client = None
        self.import_error_message = None

        if self.base_url and (self.api_key or self.provider == "ollama"):
            try:
                self.client = self.model_router.create_client(self.provider)
            except ModuleNotFoundError:
                self.import_error_message = "未安装 openai 依赖，无法生成大模型解释。"
            except Exception as exc:
                self.import_error_message = f"初始化大模型客户端失败: {exc}"
        else:
            self.import_error_message = self.selection.get("reason") or (
                "当前平台 BASE_URL 未配置，请检查 .env。"
                if not self.base_url
                else f"{self.api_key_env or 'API_KEY'} 未配置"
            )

        logger.info(
            "LLMService initialized: provider=%s model=%s base_url=%s api_key_present=%s import_ready=%s import_error=%s",
            self.get_provider_info().get("provider_label"),
            self.model,
            self.base_url,
            bool(self.api_key),
            self.import_error_message is None,
            self.import_error_message or "",
        )

    def get_provider_info(self) -> dict[str, Any]:
        """返回当前大模型平台与配置状态，供 Agent 直接回答“用的是哪家平台”。"""
        configured = bool(self.api_key)
        provider_name = self.provider_display_name or "未配置平台大模型"
        provider_label = self.provider or "未配置"
        available = bool(self.selection.get("configured", configured) or self.provider == "ollama")
        reason = str(self.selection.get("reason") or self.import_error_message or "").strip()

        return {
            "configured": configured,
            "provider_name": provider_name,
            "provider_display_name": self.provider_display_name,
            "provider_label": provider_label,
            "provider": self.provider,
            "base_url": self.base_url,
            "model": self.model,
            "model_name": self.model_display_name,
            "display_name": self.display_name,
            "api_key_configured": configured,
            "api_key_env": self.api_key_env,
            "available": available,
            "reason": reason,
            "supports_vision": self.supports_vision,
            "import_ready": self.import_error_message is None,
            "import_error_message": self.import_error_message,
            "fallback_mode": not available,
        }

    def get_current_model_info(self) -> dict[str, Any]:
        """返回当前 LLM 的精简信息，适合直接放到聊天响应里。"""
        provider_info = self.get_provider_info()
        return {
            "provider": provider_info.get("provider"),
            "provider_display_name": provider_info.get("provider_display_name"),
            "model": provider_info.get("model"),
            "model_display_name": provider_info.get("model_name"),
            "model_type": self.selection.get("model_type"),
            "supported_categories": list(self.selection.get("supported_categories") or []),
            "supported_category_labels": list(self.selection.get("supported_category_labels") or []),
            "category_summary": self.selection.get("category_summary") or "",
            "category_source": self.selection.get("category_source") or "",
            "category_reason": self.selection.get("category_reason") or "",
            "category_status": self.selection.get("category_status") or "",
            "display_name": provider_info.get("display_name"),
            "available": provider_info.get("available"),
            "reason": provider_info.get("reason"),
            "supports_vision": provider_info.get("supports_vision"),
            "base_url": provider_info.get("base_url"),
            "api_key_env": provider_info.get("api_key_env"),
        }

    def _friendly_model_error(self, exc: Exception | str | None = None) -> str:
        """把底层模型异常转换成面向用户的稳定提示。"""
        text = str(exc or self.import_error_message or "").strip()
        if self.provider == "ollama":
            return "Ollama 调用失败，请确认 ollama serve 已启动，并且已 pull 对应模型。"
        if (self.api_key_env and not self.api_key) or "API Key 未配置" in text or "API_KEY" in text:
            return f"当前平台 API Key 未配置，请检查 .env 中的 {self.api_key_env or '对应 API_KEY'}。"
        if not self.base_url or "BASE_URL" in text:
            return "当前平台 BASE_URL 未配置，请检查 .env。"
        if "未安装 openai" in text:
            return "未安装 openai 依赖，请执行 pip install -r requirements.txt。"
        return "模型请求失败，请检查 API Key、Base URL、模型 ID 和网络连接。"

    def _chat_complete(self, system_prompt: str, user_prompt: str) -> tuple[str, dict | None]:
        """执行一次通用 OpenAI-compatible 对话请求。"""
        if self.provider != "ollama" and not self.api_key:
            raise RuntimeError(self.import_error_message or f"未配置 {self.api_key_env or 'API_KEY'}")
        if self.import_error_message:
            raise RuntimeError(self.import_error_message)
        if self.client is None:
            raise RuntimeError("大模型客户端未成功初始化")

        response, _ = self.model_router.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            provider_id=self.provider,
            model_id=self.model,
            stream=False,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            timeout_seconds=self.timeout_seconds,
        )
        content = response.choices[0].message.content if response.choices else ""
        raw = response.model_dump() if hasattr(response, "model_dump") else None
        return (content or "").strip(), raw

    def generate_general_reply(self, message: str, system_context: dict | None = None) -> dict:
        """生成通用对话回复，失败时返回降级内容。"""
        system_prompt = build_general_chat_system_prompt(system_context)
        user_prompt = (
            "请根据下面这条用户消息进行自然对话。"
            "如果问题涉及真实系统状态、实验记录、模型文件、最近一次分析结果等你无法直接知道的内容，"
            "请明确说明需要通过系统工具查询，不要编造。\n\n"
            f"用户消息：{message}"
        )
        try:
            reply, raw = self._chat_complete(system_prompt, user_prompt)
            if not reply:
                reply = build_general_chat_local_reply(message, system_context=system_context)
                logger.warning(
                    "LLM general reply returned empty content: provider=%s model=%s base_url=%s",
                    self.get_provider_info().get("provider_label"),
                    self.model,
                    self.base_url,
                )
                return {
                    "success": False,
                    "reply": FALLBACK_PREFIX + reply,
                    "error_message": "大模型未返回有效内容。",
                    "raw_response": raw,
                    "model_info": self.get_current_model_info(),
                }
            return {"success": True, "reply": reply, "error_message": None, "raw_response": raw, "model_info": self.get_current_model_info()}
        except Exception as exc:
            logger.warning(
                "LLM general reply failed: provider=%s model=%s base_url=%s api_key_present=%s error_type=%s error=%s",
                self.get_provider_info().get("provider_label"),
                self.model,
                self.base_url,
                bool(self.api_key),
                type(exc).__name__,
                exc,
            )
            return {
                "success": False,
                "reply": FALLBACK_PREFIX + build_general_chat_local_reply(message, system_context=system_context),
                "error_message": self._friendly_model_error(exc),
                "raw_response": None,
                "model_info": self.get_current_model_info(),
            }

    def generate_skill_augmented_reply(
        self,
        *,
        skill_context: str,
        user_message: str,
        conversation_context: dict | None = None,
    ) -> dict:
        """基于提示词型 Skill 上下文生成回复。"""
        conversation_context = conversation_context or {}
        system_prompt = (
            build_general_chat_system_prompt(conversation_context)
            + "\n\n你正在遵循一个提示词型 Skill 的额外规则。"
            + "请优先服从下面的 Skill 上下文；如果 Skill 规则与通用对话规则冲突，以 Skill 规则为准。"
            + "如果 Skill 规则要求总结、翻译、整理、对照或提炼，请严格按照用户要求完成，不要把正常回复误报为失败。"
            + "\n\n# Skill Context\n"
            + skill_context
        )
        user_prompt = (
            "请根据上述 Skill 上下文回答用户问题。"
            "如果 Skill 上下文要求特定输出格式，请尽量遵守。"
            "不要提及你没有读取到的文件内容，不要编造不存在的脚本执行结果。"
            f"\n\n用户消息：{user_message}"
        )
        document_excerpt = str(conversation_context.get("document_excerpt") or "").strip()
        if document_excerpt:
            user_prompt += (
                "\n\n# 已提取的文件正文片段\n"
                "下面是系统从用户上传文件中提取出的正文内容，请优先基于这些内容完成总结、翻译、提炼或改写：\n\n"
                + document_excerpt
            )
        try:
            reply, raw = self._chat_complete(system_prompt, user_prompt)
            if not reply:
                logger.warning(
                    "LLM prompt-only skill reply returned empty content: provider=%s model=%s base_url=%s",
                    self.get_provider_info().get("provider_label"),
                    self.model,
                    self.base_url,
                )
                return {
                    "success": False,
                    "reply": FALLBACK_PREFIX + build_general_chat_local_reply(user_message, system_context=conversation_context),
                    "error_message": "大模型未返回有效内容。",
                    "raw_response": raw,
                    "warnings": ["大模型未返回有效内容，已回退本地回复。"],
                    "model_info": self.get_current_model_info(),
                }
            return {"success": True, "reply": reply, "error_message": None, "raw_response": raw, "warnings": [], "model_info": self.get_current_model_info()}
        except Exception as exc:
            logger.warning(
                "LLM prompt-only skill reply failed: provider=%s model=%s base_url=%s api_key_present=%s error_type=%s error=%s",
                self.get_provider_info().get("provider_label"),
                self.model,
                self.base_url,
                bool(self.api_key),
                type(exc).__name__,
                exc,
            )
            return {
                "success": False,
                "reply": FALLBACK_PREFIX + build_general_chat_local_reply(user_message, system_context=conversation_context),
                "error_message": self._friendly_model_error(exc),
                "raw_response": None,
                "warnings": [self._friendly_model_error(exc)],
                "model_info": self.get_current_model_info(),
            }

    def _sanitize_result_for_llm(self, result: dict[str, Any]) -> dict[str, Any]:
        """移除不需要发送给大模型的大数组字段。"""
        sanitized = dict(result)
        sanitized.pop("intermediate", None)
        return sanitized

    def explain_methanol_result(self, result: dict) -> str:
        """基于整理后的公开预测结果生成中文解释。"""
        public_result = self._sanitize_result_for_llm(result)
        result_summary = public_result.get("result_summary", {}) or {}
        confidence = public_result.get("confidence", {}) or {}
        model_disagreement = public_result.get("model_disagreement", {}) or {}
        professional_analysis = public_result.get("professional_analysis", {}) or {}
        model_info = public_result.get("model_info", {}) or {}
        experiment_metadata = public_result.get("experiment_metadata", {}) or {}
        pipeline = public_result.get("pipeline", []) or []
        expected_value = public_result.get("expected_value_from_filename")
        prediction_error = public_result.get("prediction_error_from_filename")

        filename_hint = ""
        if expected_value is not None:
            filename_hint = (
                f"文件名中可解析出的数值为 {expected_value:.4f}，"
                f"若该数值代表真实浓度，则本次融合预测与该数值的差值约为 {float(prediction_error):.4f}。"
            )

        system_prompt = (
            "你是一名有拉曼光谱和化学计量学经验的分析人员，正在向实验人员解释模型预测结果。"
            "请用自然、细致、容易理解的中文回答，像老师给学生解释，或者工程师给实验人员做分析。"
            "不要机械复述字段，不要编造仪器参数、样品来源或实验条件，不要声称结果一定准确。"
            "只能基于用户提供的 result 和 professional_analysis 解释，某项数据为空时要说明当前未提供。"
            "可以使用 Markdown，但风格要自然，不要写得像模板。"
        )
        user_prompt = (
            "请根据以下结构化结果，写一份更像人工分析意见的中文解释，控制在约 500 到 900 字。\n\n"
            f"样品文件名: {public_result.get('sample_file', '')}\n"
            f"融合预测值: {float(public_result.get('fusion_prediction', 0.0)):.4f} {public_result.get('unit', '')}\n"
            f"SVR预测值: {float(public_result.get('svr_prediction', 0.0)):.4f} {public_result.get('unit', '')}\n"
            f"RF预测值: {float(public_result.get('rf_prediction', 0.0)):.4f} {public_result.get('unit', '')}\n"
            f"可信度信息: {confidence}\n"
            f"模型差异信息: {model_disagreement}\n"
            f"专业光谱分析: {professional_analysis}\n"
            f"模型信息: {model_info}\n"
            f"实验信息: {experiment_metadata}\n"
            f"结果摘要: {result_summary}\n"
            f"处理流程: {' → '.join(pipeline)}\n"
            f"辅助文件名提示: {filename_hint or '未从文件名中解析出可参考的真实值。'}\n\n"
            "请按下面思路组织：\n"
            "1. 用自然的标题，例如“## 结果怎么理解”“## 这个结果可信在哪里”“## 需要注意什么”“## 给实验人员的建议”。\n"
            "2. 解释融合预测值与 SVR、RF 的关系，说明两个模型不完全一样是正常现象，但差异过大要提醒复核。\n"
            "3. 解释“可信度正常”只表示样本特征与训练集更接近，不代表结果百分之百准确。\n"
            "4. 解释模型差异时要区分低浓度和高浓度：低浓度更关注绝对差异，高浓度更应参考相对差异。\n"
            "5. 如果 absolute_difference 大于 abs_threshold，但 relative_difference 小于 rel_threshold，应说明“绝对差异看起来大于绝对阈值，但由于当前浓度较高，更应参考相对差异；当前相对差异低于阈值，因此模型一致性仍可接受”。\n"
            "6. 禁止把不存在或超阈值的指标解释成正常；如果模型差异 warning=true，要温和但明确地建议人工复核；如果 warning=false，要说明两个模型一致性较好。\n"
            "7. 结合专业光谱分析中的主要峰、信噪比、基线质量和历史相似样品信息。如果某项数据为空，要说当前未提供。\n"
            "8. 要说明当前模型版本；如果有实验信息，也可以适度引用，但不能编造未提供的仪器条件。\n"
            "9. 如果文件名中的数值可能代表真实浓度，可以谨慎说明“如果文件名中的数字代表真实值，那么预测与该值的差异大约是多少”，但不要把它当成确定事实。\n"
            "10. 只有当 similarity_analysis 确实返回相似记录时，才能说有历史相似样品；不能把 mock、test、demo 记录当成真实参考。\n"
            "11. 对 professional_analysis 的解释保持谨慎：光谱质量好不等于预测绝对准确，基线风险只是提示，需要结合图像人工复核。\n"
            "12. 最后给 2 到 4 条对实验人员有用的建议，比如检查原始光谱噪声、观察基线修正是否合理、做重复样本验证等。\n"
            "13. 语言尽量像专业人员对人解释，不要像复制字段。"
        )

        try:
            content, _ = self._chat_complete(system_prompt, user_prompt)
            return content or "大模型未返回有效解释内容。"
        except Exception as exc:
            logger.warning(
                "LLM methanol explanation failed: provider=%s model=%s base_url=%s api_key_present=%s error_type=%s error=%s",
                self.get_provider_info().get("provider_label"),
                self.model,
                self.base_url,
                bool(self.api_key),
                type(exc).__name__,
                exc,
            )
            return f"{FALLBACK_PREFIX}大模型解释生成失败: {exc}"
