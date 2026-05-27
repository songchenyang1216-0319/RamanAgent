"""Tavily 联网搜索 provider。"""

from __future__ import annotations

import os
from typing import Any

from .base import SearchProvider


def _normalize_bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class TavilyProvider(SearchProvider):
    """Tavily 搜索实现，按需加载 tavily-python。"""

    name = "tavily"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        search_depth: str | None = None,
        include_answer: bool | None = None,
        include_raw_content: bool | None = None,
        include_images: bool | None = None,
        timeout_seconds: int = 20,
    ) -> None:
        self.api_key = str(api_key or os.getenv("TAVILY_API_KEY") or "").strip()
        self.base_url = str(base_url or os.getenv("TAVILY_BASE_URL") or "").strip()
        self.search_depth = str(search_depth or os.getenv("TAVILY_SEARCH_DEPTH") or "basic").strip() or "basic"
        self.include_answer = _normalize_bool(
            include_answer if include_answer is not None else os.getenv("TAVILY_INCLUDE_ANSWER"),
            default=False,
        )
        self.include_raw_content = _normalize_bool(
            include_raw_content if include_raw_content is not None else os.getenv("TAVILY_INCLUDE_RAW_CONTENT"),
            default=False,
        )
        self.include_images = _normalize_bool(
            include_images if include_images is not None else os.getenv("TAVILY_INCLUDE_IMAGES"),
            default=False,
        )
        self.timeout_seconds = max(3, int(timeout_seconds or 20))
        self._last_response: dict[str, Any] | None = None

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def configuration_error(self) -> str:
        if not self.api_key:
            return "联网搜索已启用 Tavily，但 TAVILY_API_KEY 未配置。请在 .env 中填写 TAVILY_API_KEY。"
        return ""

    def _load_client(self):
        try:
            from tavily import TavilyClient
        except Exception as exc:  # pragma: no cover - 依赖缺失时走友好错误
            raise RuntimeError("未安装 tavily-python 依赖，请执行 pip install -r requirements.txt。") from exc

        client_kwargs: dict[str, Any] = {"api_key": self.api_key}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url
        try:
            return TavilyClient(**client_kwargs)
        except TypeError:
            client_kwargs.pop("base_url", None)
            return TavilyClient(**client_kwargs)

    def _normalize_results(self, response: dict[str, Any], max_results: int) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for raw in list(response.get("results") or [])[: max(1, int(max_results or 5))]:
            if not isinstance(raw, dict):
                continue
            content = str(raw.get("content") or raw.get("raw_content") or "").strip()
            items.append(
                {
                    "title": str(raw.get("title") or raw.get("url") or "未命名结果").strip(),
                    "url": str(raw.get("url") or "").strip(),
                    "snippet": content,
                    "source": "tavily",
                    "score": float(raw.get("score") or 0.0),
                    "published_at": raw.get("published_at") or raw.get("published_time") or None,
                }
            )
        return items

    def search_bundle(self, query: str, max_results: int = 5) -> dict[str, Any]:
        query = str(query or "").strip()
        if not query:
            raise RuntimeError("搜索关键词不能为空。")
        if not self.api_key:
            raise RuntimeError(self.configuration_error())

        client = self._load_client()
        params = {
            "query": query,
            "max_results": max(1, min(int(max_results or 5), 20)),
            "search_depth": self.search_depth,
            "include_answer": self.include_answer,
            "include_raw_content": self.include_raw_content,
            "include_images": self.include_images,
        }
        try:
            try:
                response = client.search(**params, timeout=self.timeout_seconds)
            except TypeError:
                response = client.search(**params)
        except Exception as exc:
            raise RuntimeError(f"联网搜索失败：{exc}") from exc

        if not isinstance(response, dict):
            raise RuntimeError("Tavily 返回了无法解析的结果。")

        self._last_response = response
        items = self._normalize_results(response, params["max_results"])
        return {
            "query": query,
            "items": items,
            "total": len(items),
            "source": self.name,
            "used_provider": self.name,
            "answer": response.get("answer"),
            "request_id": response.get("request_id"),
            "response_time": response.get("response_time"),
            "search_depth": self.search_depth,
            "include_answer": self.include_answer,
            "include_raw_content": self.include_raw_content,
            "include_images": self.include_images,
            "raw_response": response,
        }

    def search(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
        return list(self.search_bundle(query, max_results=max_results).get("items") or [])
