from __future__ import annotations

import json
import re
from typing import Any


def strip_markdown_fence(text: str) -> str:
    value = str(text or "").strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?", "", value, flags=re.IGNORECASE).strip()
        value = re.sub(r"```$", "", value).strip()
    return value


def extract_json_object(text: str) -> str:
    value = strip_markdown_fence(text)
    if value.startswith("{") and value.endswith("}"):
        return value
    start = value.find("{")
    end = value.rfind("}")
    if start >= 0 and end > start:
        return value[start : end + 1]
    return value


def repair_json_text(text: str) -> str:
    """Best-effort repair for common LLM JSON formatting mistakes."""

    value = extract_json_object(text)
    value = value.replace("\ufeff", "").strip()
    value = re.sub(r",\s*([}\]])", r"\1", value)
    value = value.replace("“", '"').replace("”", '"').replace("’", "'")
    return value


def loads_json_with_repair(text: str) -> tuple[dict[str, Any], str]:
    repaired = repair_json_text(text)
    payload = json.loads(repaired)
    if not isinstance(payload, dict):
        raise ValueError("LLM Planner 输出 JSON 顶层必须是对象。")
    return payload, repaired

