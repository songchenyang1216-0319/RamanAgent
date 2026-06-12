from __future__ import annotations

from pathlib import Path

from backend.services.ocr import OCRService

from .base import BaseFileProcessor, ProcessedFile


class PdfFileProcessor(BaseFileProcessor):
    file_type = "pdf"
    supported_suffixes = {".pdf"}

    def process(self, path: Path, *, file_id: str | None = None, **_: object) -> ProcessedFile:
        try:
            from pypdf import PdfReader
        except ModuleNotFoundError:
            return self.failure(path, "当前环境缺少 pypdf，暂时无法提取 PDF 正文。")
        try:
            reader = PdfReader(str(path))
            pages = []
            chunks = []
            empty_pages = []
            for index, page in enumerate(reader.pages, start=1):
                text = (page.extract_text() or "").strip()
                if text:
                    pages.append(text)
                    chunks.extend(self.make_chunks(text, file_id=file_id, section="pdf", page=str(index)))
                else:
                    empty_pages.append(index)
            full_text = "\n\n".join(pages)
        except Exception as exc:
            return self.failure(path, f"PDF 文件解析失败：{exc}")
        ocr_status = OCRService().get_status()
        ocr_required = bool(reader.pages) and not full_text.strip()
        return ProcessedFile(
            success=True,
            file_type=self.file_type,
            filename=path.name,
            summary=(
                f"已解析 PDF，共 {len(reader.pages)} 页，提取到 {len(full_text)} 个字符。"
                + (" 该 PDF 可能是扫描件，需要 OCR 才能读取正文。" if ocr_required else "")
            ),
            metadata={
                "pages": len(reader.pages),
                "characters": len(full_text),
                "empty_text_pages": empty_pages[:50],
                "empty_text_page_count": len(empty_pages),
                "ocr_required": ocr_required,
                "ocr_available": bool(ocr_status.get("available")),
                "ocr_status": ocr_status,
                "suffix": path.suffix.lower(),
            },
            preview=full_text[:3000],
            chunks=chunks,
        )
