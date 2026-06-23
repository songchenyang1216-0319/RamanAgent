from __future__ import annotations

import logging
import os
from email.utils import format_datetime
from datetime import datetime, timezone

from fastapi import Response


logger = logging.getLogger(__name__)
_warned_keys: set[str] = set()


def legacy_deprecation_enabled() -> bool:
    return str(os.getenv("LEGACY_API_DEPRECATION_ENABLED", "true")).strip().lower() not in {"0", "false", "no", "off"}


def apply_deprecation_headers(response: Response, *, legacy_path: str, successor_path: str) -> None:
    if not legacy_deprecation_enabled():
        return
    response.headers["Deprecation"] = "true"
    sunset = _sunset_header_value()
    if sunset:
        response.headers["Sunset"] = sunset
    response.headers["Link"] = f"<{successor_path}>; rel=\"successor-version\""
    warn_once(legacy_path=legacy_path, successor_path=successor_path)


def warn_once(*, legacy_path: str, successor_path: str) -> None:
    key = f"{legacy_path}->{successor_path}"
    if key in _warned_keys:
        return
    _warned_keys.add(key)
    logger.warning("Legacy API is deprecated: %s; successor=%s", legacy_path, successor_path)


def _sunset_header_value() -> str | None:
    raw = str(os.getenv("LEGACY_API_SUNSET_DATE", "2026-12-31") or "").strip()
    if not raw:
        return None
    try:
        if len(raw) == 10:
            dt = datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        return format_datetime(dt, usegmt=True)
    except ValueError:
        logger.warning("Ignoring invalid LEGACY_API_SUNSET_DATE value.")
        return None
