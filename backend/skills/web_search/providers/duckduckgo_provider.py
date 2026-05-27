"""DuckDuckGo HTML 联网搜索 provider。"""

from __future__ import annotations

import html
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from .base import SearchProvider


SEARCH_ENDPOINT = "https://html.duckduckgo.com/html/"


def _extract_results(html_text: str, limit: int = 5) -> list[dict]:
    items: list[dict] = []
    pattern = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>.*?'
        r'<a[^>]+class="result__snippet"[^>]*>(?P<snippet>.*?)</a>',
        re.S,
    )
    for match in pattern.finditer(html_text):
        raw_url = html.unescape(match.group("url"))
        title = re.sub(r"<.*?>", "", html.unescape(match.group("title"))).strip()
        snippet = re.sub(r"<.*?>", "", html.unescape(match.group("snippet"))).strip()
        if not title or not raw_url:
            continue
        items.append(
            {
                "title": title,
                "url": raw_url,
                "snippet": snippet,
                "source": "duckduckgo",
                "score": 1.0,
                "published_at": None,
            }
        )
        if len(items) >= limit:
            break
    return items


class DuckDuckGoProvider(SearchProvider):
    """DuckDuckGo HTML 搜索实现。"""

    name = "duckduckgo"

    def __init__(self, timeout_seconds: int = 12) -> None:
        self.timeout_seconds = max(3, int(timeout_seconds or 12))

    def search(self, query: str, max_results: int = 5) -> list[dict]:
        query = str(query or "").strip()
        if not query:
            raise RuntimeError("搜索关键词不能为空。")
        try:
            url = f"{SEARCH_ENDPOINT}?q={quote_plus(query)}"
            request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(request, timeout=self.timeout_seconds) as response:
                html_text = response.read().decode("utf-8", errors="ignore")
            return _extract_results(html_text, limit=max(1, min(int(max_results or 5), 10)))
        except (HTTPError, URLError) as exc:
            raise RuntimeError(f"联网搜索失败：{exc}") from exc
        except Exception as exc:
            raise RuntimeError(f"联网搜索失败：{exc}") from exc

    def search_bundle(self, query: str, max_results: int = 5) -> dict:
        items = self.search(query, max_results=max_results)
        return {
            "query": query,
            "items": items,
            "total": len(items),
            "source": self.name,
            "used_provider": self.name,
            "answer": None,
            "request_id": None,
            "response_time": None,
        }
