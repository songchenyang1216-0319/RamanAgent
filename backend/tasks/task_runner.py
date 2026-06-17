from __future__ import annotations

from typing import Any, Callable


TaskCallable = Callable[[dict[str, Any], Callable[[str, str, dict[str, Any] | None], None]], dict[str, Any]]

