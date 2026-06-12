from __future__ import annotations

from pathlib import Path

from .base import BaseFileProcessor, ProcessedFile


TEXT_SUFFIXES = {".txt", ".log", ".yaml", ".yml"}


class TextFileProcessor(BaseFileProcessor):
    file_type = "text"
    supported_suffixes = TEXT_SUFFIXES

    def process(self, path: Path, *, file_id: str | None = None, **_: object) -> ProcessedFile:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return self.failure(path, f"文本文件读取失败：{exc}")
        preview = text[:2000]
        chunks = self.make_chunks(text, file_id=file_id, section="text")
        return ProcessedFile(
            success=True,
            file_type=self.file_type,
            filename=path.name,
            summary=f"已读取文本文件，共 {len(text)} 个字符。",
            metadata={"characters": len(text), "suffix": path.suffix.lower()},
            preview=preview,
            chunks=chunks,
        )
