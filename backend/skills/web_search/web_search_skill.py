"""联网搜索 Skill。"""

from __future__ import annotations

import os
from typing import Any

from backend.agent.prompts.general_chat_prompt import build_general_chat_local_reply
from backend.services.llm_service import LLMService

from ..base import BaseSkill, SkillResult
from .providers import DuckDuckGoProvider, TavilyProvider


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(str(value).strip())
    except Exception:
        return default


def _env_text(name: str, default: str = "") -> str:
    return str(os.getenv(name, default) or default).strip()


def _truncate(text: str, limit: int = 260) -> str:
    normalized = str(text or "").strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 3)] + "..."


class WebSearchSkill(BaseSkill):
    """正式联网搜索 Skill。"""

    name = "web-search"
    display_name = "联网搜索"
    description = "搜索互联网最新信息，并把结果作为上下文提供给大模型回答。"
    category = "搜索"
    version = "1.0.0"
    requires_file = False
    supported_file_types: list[str] = []
    usage = "输入需要最新信息的问题，或明确说“联网查一下/搜索一下”即可。"

    def __init__(self) -> None:
        self.enabled = _env_bool("WEB_SEARCH_ENABLED", True)
        self.available = bool(self.enabled)
        self.unavailable_reason = "" if self.available else "WEB_SEARCH_ENABLED=false"
        self.provider_name = _env_text("WEB_SEARCH_PROVIDER", "tavily").lower() or "tavily"
        self.fallback_provider_name = _env_text("WEB_SEARCH_FALLBACK_PROVIDER", "").lower() or ""
        self.max_results = max(1, min(_env_int("WEB_SEARCH_MAX_RESULTS", 5), 10))
        self.timeout_seconds = max(3, _env_int("WEB_SEARCH_TIMEOUT_SECONDS", 20))
        self.require_citations = _env_bool("WEB_SEARCH_REQUIRE_CITATIONS", True)
        self.actions = [
            {
                "name": "search",
                "display_name": "搜索网页",
                "description": "根据关键词搜索网页，返回标题、链接和摘要。",
                "enabled": True,
                "available": True,
                "status": "ready",
                "unavailable_reason": "",
            },
            {
                "name": "answer_with_sources",
                "display_name": "带来源回答",
                "description": "基于搜索结果生成带来源的回答。",
                "enabled": True,
                "available": True,
                "status": "ready",
                "unavailable_reason": "",
            },
        ]

    def _build_provider(self):
        if self.provider_name == "duckduckgo":
            return DuckDuckGoProvider(timeout_seconds=self.timeout_seconds), None

        if self.provider_name == "tavily":
            provider = TavilyProvider(timeout_seconds=self.timeout_seconds)
            if provider.is_configured():
                return provider, None
            if self.fallback_provider_name == "duckduckgo":
                return DuckDuckGoProvider(timeout_seconds=self.timeout_seconds), None
            return provider, provider.configuration_error()

        if self.fallback_provider_name == "duckduckgo":
            return DuckDuckGoProvider(timeout_seconds=self.timeout_seconds), None

        return None, f"WEB_SEARCH_PROVIDER={self.provider_name} 不受支持。"

    def _build_search_context(self, query: str, provider_name: str, items: list[dict[str, Any]], answer: str | None = None) -> str:
        lines = [
            "你正在基于联网搜索结果回答用户问题。",
            f"搜索提供商：{provider_name}",
            f"搜索关键词：{query}",
            "",
            "来源列表：",
        ]
        for idx, item in enumerate(items[: self.max_results], start=1):
            title = str(item.get("title") or "未命名结果").strip()
            url = str(item.get("url") or "").strip()
            snippet = str(item.get("snippet") or "").strip()
            lines.append(f"{idx}. {title}")
            if url:
                lines.append(f"   URL: {url}")
            if snippet:
                lines.append(f"   摘要: {snippet}")
        if answer:
            lines.extend(["", f"Tavily 参考答案：{answer}"])
        lines.extend(
            [
                "",
                "要求：",
                "1. 用中文给出简明、自然、可读的最终回答。",
                "2. 优先依据来源内容，不要编造。",
                "3. 如果信息不充分，请明确说明不确定。",
                "4. 回答末尾可以简要提及参考了哪些来源。",
            ]
        )
        return "\n".join(lines)

    def _build_failure(
        self,
        query: str,
        message: str,
        suggestion: str,
        provider_name: str | None = None,
        action_name: str = "search",
    ) -> SkillResult:
        payload = {
            "query": query,
            "items": [],
            "total": 0,
            "used_provider": provider_name or self.provider_name,
            "provider": provider_name or self.provider_name,
            "error_code": "WEB_SEARCH_FAILED",
            "message": message,
            "suggestion": suggestion,
            "source": provider_name or self.provider_name,
        }
        return SkillResult(
            success=False,
            skill_name=self.name,
            action_name=action_name,
            summary=message,
            data=payload,
            errors=[message],
        )

    def _build_local_answer(self, query: str, items: list[dict[str, Any]], provider_name: str) -> str:
        lines = [f"我帮你联网搜索到 {len(items)} 条相关结果，搜索提供商是 {provider_name}。"]
        for item in items[:3]:
            title = str(item.get("title") or "未命名结果").strip()
            snippet = str(item.get("snippet") or "").strip()
            if title:
                lines.append(f"- {title}")
            if snippet:
                lines.append(f"  {snippet}")
        if not items:
            lines.append("但当前没有拿到可引用的来源。")
        return "\n".join(lines)

    def _answer_with_sources(
        self,
        *,
        query: str,
        items: list[dict[str, Any]],
        provider_name: str,
        conversation_context: dict[str, Any] | None = None,
        provider_id: str | None = None,
        model_id: str | None = None,
        user_id: str | None = None,
        conversation_id: str | None = None,
        answer_hint: str | None = None,
    ) -> dict[str, Any]:
        skill_context = self._build_search_context(query, provider_name, items, answer=answer_hint)
        llm_result = LLMService(
            provider_id=provider_id,
            model_id=model_id,
            user_id=user_id,
            conversation_id=conversation_id,
        ).generate_skill_augmented_reply(
            skill_context=skill_context,
            user_message=query,
            conversation_context=conversation_context or {},
        )
        reply = str(llm_result.get("reply") or "").strip()
        if not reply:
            reply = self._build_local_answer(query, items, provider_name)
        return {
            "reply": reply,
            "model_info": llm_result.get("model_info") or {},
            "llm_success": bool(llm_result.get("success")),
            "llm_error": llm_result.get("error_message"),
            "raw_response": llm_result.get("raw_response"),
        }

    def run(self, **kwargs: Any) -> SkillResult:
        action_name = str(kwargs.get("action_name") or "search").strip() or "search"
        query = str(kwargs.get("query") or kwargs.get("message") or kwargs.get("original_message") or "").strip()
        max_results = int(kwargs.get("max_results") or self.max_results or 5)
        max_results = max(1, min(max_results, 10))

        if not self.available:
            return self._build_failure(
                query,
                "当前问题需要联网搜索，但 web-search skill 已禁用，请在 Skills 管理中启用。",
                "请在 Skills 管理中启用 web-search skill。",
                provider_name=self.provider_name,
                action_name=action_name,
            )

        provider, provider_error = self._build_provider()
        if provider_error:
            return self._build_failure(
                query,
                provider_error,
                "请检查 WEB_SEARCH_PROVIDER、WEB_SEARCH_FALLBACK_PROVIDER 或 TAVILY_API_KEY 配置。",
                provider_name=getattr(provider, "name", self.provider_name) if provider else self.provider_name,
                action_name=action_name,
            )
        if provider is None:
            return self._build_failure(
                query,
                "未找到可用的联网搜索 provider。",
                "请检查 WEB_SEARCH_PROVIDER 配置。",
                provider_name=self.provider_name,
                action_name=action_name,
            )

        try:
            bundle = provider.search_bundle(query, max_results=max_results)
        except Exception as exc:
            message = str(exc).strip() or "联网搜索失败。"
            suggestion = "请检查 TAVILY_API_KEY、网络连接或 WEB_SEARCH_PROVIDER 配置。"
            if provider.name == "duckduckgo":
                suggestion = "请检查网络连接或稍后重试。"
            return self._build_failure(query, message, suggestion, provider_name=provider.name, action_name=action_name)

        items = list(bundle.get("items") or [])
        if self.require_citations and not items:
            return self._build_failure(
                query,
                "联网搜索没有返回可引用的结果。",
                "请更换关键词后重试，或检查 WEB_SEARCH_MAX_RESULTS / WEB_SEARCH_PROVIDER 配置。",
                provider_name=str(bundle.get("used_provider") or provider.name),
                action_name=action_name,
            )

        used_provider = str(bundle.get("used_provider") or provider.name or self.provider_name).strip() or provider.name
        answer = bundle.get("answer")
        if action_name == "answer_with_sources":
            answered = self._answer_with_sources(
                query=query,
                items=items,
                provider_name=used_provider,
                conversation_context=kwargs.get("conversation_context") if isinstance(kwargs.get("conversation_context"), dict) else {},
                provider_id=str(kwargs.get("provider_id") or "").strip() or None,
                model_id=str(kwargs.get("model_id") or "").strip() or None,
                user_id=str(kwargs.get("user_id") or "").strip() or None,
                conversation_id=str(kwargs.get("conversation_id") or "").strip() or None,
                answer_hint=str(answer or "").strip() or None,
            )
            reply = answered["reply"]
            summary = _truncate(reply, 320)
            data = {
                "query": query,
                "items": items,
                "total": len(items),
                "used_provider": used_provider,
                "provider": used_provider,
                "source": used_provider,
                "answer": reply,
                "search_answer": answer,
                "request_id": bundle.get("request_id"),
                "response_time": bundle.get("response_time"),
                "search_depth": bundle.get("search_depth"),
                "include_answer": bundle.get("include_answer"),
                "include_raw_content": bundle.get("include_raw_content"),
                "include_images": bundle.get("include_images"),
                "model_info": answered.get("model_info") or {},
                "llm_success": answered.get("llm_success"),
                "llm_error": answered.get("llm_error"),
            }
            return SkillResult(
                success=True,
                skill_name=self.name,
                action_name=action_name,
                summary=summary,
                data=data,
                errors=[],
            )

        reply = self._build_local_answer(query, items, used_provider)
        summary = f"联网搜索完成，共找到 {len(items)} 条结果。"
        data = {
            "query": query,
            "items": items,
            "total": len(items),
            "used_provider": used_provider,
            "provider": used_provider,
            "source": used_provider,
            "answer": answer,
            "request_id": bundle.get("request_id"),
            "response_time": bundle.get("response_time"),
            "search_depth": bundle.get("search_depth"),
            "include_answer": bundle.get("include_answer"),
            "include_raw_content": bundle.get("include_raw_content"),
            "include_images": bundle.get("include_images"),
            "reply_text": reply,
        }
        return SkillResult(
            success=True,
            skill_name=self.name,
            action_name=action_name,
            summary=summary,
            data=data,
            errors=[],
        )
