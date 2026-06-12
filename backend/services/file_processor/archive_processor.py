from __future__ import annotations

from pathlib import Path
from zipfile import BadZipFile, ZipFile

from .base import BaseFileProcessor, ProcessedFile


class ArchiveFileProcessor(BaseFileProcessor):
    file_type = "archive"
    supported_suffixes = {".zip"}

    def process(self, path: Path, *, file_id: str | None = None, **_: object) -> ProcessedFile:
        try:
            with ZipFile(path) as archive:
                safe_entries = []
                blocked_entries = []
                for info in archive.infolist():
                    name = info.filename.replace("\\", "/")
                    if name.startswith("/") or ".." in Path(name).parts:
                        blocked_entries.append(name)
                        continue
                    if not info.is_dir():
                        safe_entries.append({"filename": name, "size": info.file_size})
        except BadZipFile:
            return self.failure(path, "ZIP 文件已损坏或格式不正确。")
        except Exception as exc:
            return self.failure(path, f"ZIP 文件读取失败：{exc}")
        listing = "\n".join(f"- {item['filename']} ({item['size']} bytes)" for item in safe_entries[:200])
        metadata = {
            "safe_file_count": len(safe_entries),
            "blocked_entries": blocked_entries[:50],
            "suffix": path.suffix.lower(),
            "execution": "disabled",
        }
        return ProcessedFile(
            success=True,
            file_type=self.file_type,
            filename=path.name,
            summary=f"已读取 ZIP 文件索引，共 {len(safe_entries)} 个安全文件，拦截 {len(blocked_entries)} 个可疑路径。",
            metadata=metadata,
            preview=listing,
            chunks=self.make_chunks(listing, file_id=file_id, section="zip-index"),
        )
