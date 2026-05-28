from __future__ import annotations

from typing import Any


class BaseProvider:
    provider_id = "base"

    def chat(self, messages: list[dict[str, Any]], model: str | None = None, temperature: float = 0.7, stream: bool = False):
        raise NotImplementedError

