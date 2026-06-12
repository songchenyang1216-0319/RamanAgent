from __future__ import annotations

from pathlib import Path

from .base import BaseFileProcessor, ProcessedFile


class CodeFileProcessor(BaseFileProcessor):
    file_type = "code"
    supported_suffixes = {
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".java",
        ".go",
        ".html",
        ".css",
        ".sql",
        ".sh",
        ".ps1",
    }

    def process(self, path: Path, *, file_id: str | None = None, **_: object) -> ProcessedFile:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return self.failure(path, f"代码文件读取失败：{exc}")
        lines = text.splitlines()
        return ProcessedFile(
            success=True,
            file_type=self.file_type,
            filename=path.name,
            summary=f"已读取代码文件，共 {len(lines)} 行。系统只会分析文本，不会自动执行上传代码。",
            metadata={"lines": len(lines), "suffix": path.suffix.lower(), "execution": "disabled"},
            preview="\n".join(lines[:80]),
            chunks=self.make_chunks(text, file_id=file_id, section="code"),
        )
