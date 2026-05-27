"""联网搜索 provider 基础接口。"""

from __future__ import annotations

from typing import Any


class SearchProvider:
    """搜索 provider 基础类。"""

    name = "base"

    def search(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
        raise NotImplementedError

    def search_bundle(self, query: str, max_results: int = 5) -> dict[str, Any]:
        items = self.search(query, max_results=max_results)
        return {
            "query": query,
            "items": items,
            "total": len(items),
            "source": self.name,
            "used_provider": self.name,
        }
