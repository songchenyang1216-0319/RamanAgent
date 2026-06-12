from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base import BaseFileProcessor, ProcessedFile


class JsonFileProcessor(BaseFileProcessor):
    file_type = "json"
    supported_suffixes = {".json"}

    def process(self, path: Path, *, file_id: str | None = None, **_: object) -> ProcessedFile:
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
            data: Any = json.loads(raw)
        except Exception as exc:
            return self.failure(path, f"JSON 文件解析失败：{exc}")
        if isinstance(data, dict):
            shape = {"type": "object", "keys": list(data.keys())[:50]}
        elif isinstance(data, list):
            shape = {"type": "array", "length": len(data)}
        else:
            shape = {"type": type(data).__name__}
        pretty = json.dumps(data, ensure_ascii=False, indent=2)[:12000]
        return ProcessedFile(
            success=True,
            file_type=self.file_type,
            filename=path.name,
            summary=f"已解析 JSON 文件，顶层类型为 {shape['type']}。",
            metadata={"shape": shape, "suffix": path.suffix.lower()},
            preview=pretty[:2000],
            chunks=self.make_chunks(pretty, file_id=file_id, section="json"),
        )
