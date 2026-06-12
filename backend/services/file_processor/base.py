from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4


MAX_CHUNK_CHARS = 1800


@dataclass
class FileChunk:
    chunk_id: str
    source_file_id: str | None
    page: str | None
    section: str | None
    text: str
    token_estimate: int
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProcessedFile:
    success: bool
    file_type: str
    filename: str
    summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    preview: str = ""
    chunks: list[FileChunk] = field(default_factory=list)
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["chunks"] = [chunk.to_dict() for chunk in self.chunks]
        return payload


class BaseFileProcessor:
    file_type = "file"
    supported_suffixes: set[str] = set()

    def can_process(self, path: Path) -> bool:
        return path.suffix.lower() in self.supported_suffixes

    def process(self, path: Path, *, file_id: str | None = None, **_: Any) -> ProcessedFile:
        raise NotImplementedError

    def make_chunks(self, text: str, *, file_id: str | None = None, section: str | None = None, page: str | None = None) -> list[FileChunk]:
        normalized = str(text or "").replace("\r\n", "\n").strip()
        if not normalized:
            return []
        chunks: list[FileChunk] = []
        start = 0
        while start < len(normalized):
            part = normalized[start : start + MAX_CHUNK_CHARS].strip()
            if part:
                chunks.append(
                    FileChunk(
                        chunk_id=uuid4().hex,
                        source_file_id=file_id,
                        page=page,
                        section=section,
                        text=part,
                        token_estimate=max(1, len(part) // 4),
                    )
                )
            start += MAX_CHUNK_CHARS
        return chunks

    def failure(self, path: Path, message: str) -> ProcessedFile:
        return ProcessedFile(
            success=False,
            file_type=self.file_type,
            filename=path.name,
            error_message=message,
            summary=message,
            metadata={"suffix": path.suffix.lower()},
        )
