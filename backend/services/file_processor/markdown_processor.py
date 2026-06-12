from __future__ import annotations

import re
from pathlib import Path

from .base import BaseFileProcessor, ProcessedFile


class MarkdownFileProcessor(BaseFileProcessor):
    file_type = "markdown"
    supported_suffixes = {".md", ".markdown"}

    def process(self, path: Path, *, file_id: str | None = None, **_: object) -> ProcessedFile:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return self.failure(path, f"Markdown 文件读取失败：{exc}")
        headings = [match.group(1).strip() for match in re.finditer(r"^#{1,6}\s+(.+)$", text, flags=re.MULTILINE)]
        return ProcessedFile(
            success=True,
            file_type=self.file_type,
            filename=path.name,
            summary=f"已读取 Markdown 文件，识别到 {len(headings)} 个标题。",
            metadata={"characters": len(text), "headings": headings[:30], "suffix": path.suffix.lower()},
            preview=text[:2000],
            chunks=self.make_chunks(text, file_id=file_id, section="markdown"),
        )
