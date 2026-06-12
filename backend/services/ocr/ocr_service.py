from __future__ import annotations

import os
from pathlib import Path
from typing import Any


class OCRService:
    """Configurable OCR capability with safe, explicit fallbacks."""

    def __init__(self, provider: str | None = None, language: str | None = None) -> None:
        self.provider = str(provider or os.getenv("OCR_PROVIDER") or "auto").strip().lower()
        self.language = str(language or os.getenv("OCR_LANGUAGE") or "eng+chi_sim").strip()
        self.max_pages = max(1, int(os.getenv("OCR_MAX_PAGES", "10") or 10))

    def get_status(self) -> dict[str, Any]:
        if self.provider in {"none", "disabled", "off"}:
            return {
                "available": False,
                "provider": "none",
                "configured_provider": self.provider,
                "language": self.language,
                "reason": "OCR_PROVIDER=none，OCR 已显式关闭。",
                "safe_mode": True,
            }
        if self.provider == "paddleocr":
            try:
                import paddleocr  # type: ignore  # noqa: F401

                return {
                    "available": True,
                    "provider": "paddleocr",
                    "configured_provider": self.provider,
                    "language": self.language,
                    "reason": "",
                    "safe_mode": True,
                }
            except Exception:
                return {
                    "available": False,
                    "provider": "paddleocr",
                    "configured_provider": self.provider,
                    "language": self.language,
                    "reason": "OCR_PROVIDER=paddleocr，但当前环境未安装 paddleocr。",
                    "safe_mode": True,
                }
        try:
            import pytesseract  # type: ignore  # noqa: F401

            return {
                "available": True,
                "provider": "pytesseract",
                "configured_provider": self.provider,
                "language": self.language,
                "reason": "",
                "safe_mode": True,
            }
        except Exception:
            return {
                "available": False,
                "provider": "pytesseract" if self.provider == "pytesseract" else None,
                "configured_provider": self.provider,
                "language": self.language,
                "reason": "当前未配置 OCR 引擎；扫描件或图片文字暂不能自动识别。",
                "safe_mode": True,
            }

    def extract_image_text(self, path: str | Path) -> dict[str, Any]:
        status = self.get_status()
        if not status.get("available"):
            return {"success": False, "text": "", "status": status, "error_message": status.get("reason")}
        try:
            from PIL import Image

            if status.get("provider") == "paddleocr":
                return self._extract_image_text_with_paddle(path, status)
            import pytesseract  # type: ignore

            with Image.open(path) as image:
                text = pytesseract.image_to_string(image, lang=self.language)
            return {"success": True, "text": text or "", "status": status, "error_message": None, "pages": [{"page": 1, "text": text or ""}]}
        except Exception as exc:
            return {"success": False, "text": "", "status": status, "error_message": f"OCR 识别失败：{exc}"}

    def extract_pdf_text(self, path: str | Path, *, page_range: str | None = None) -> dict[str, Any]:
        status = self.get_status()
        if not status.get("available"):
            return {"success": False, "text": "", "status": status, "pages": [], "error_message": status.get("reason")}
        try:
            from pdf2image import convert_from_path  # type: ignore
        except Exception as exc:
            return {
                "success": False,
                "text": "",
                "status": status,
                "pages": [],
                "error_message": "PDF OCR 需要安装 pdf2image 和本机 Poppler。当前环境未满足依赖。",
                "detail": str(exc),
            }

        try:
            pages = self._parse_page_range(page_range, max_pages=self.max_pages)
            images = convert_from_path(str(path), first_page=pages[0] if pages else None, last_page=pages[-1] if pages else None)
            page_results = []
            for index, image in enumerate(images[: self.max_pages], start=pages[0] if pages else 1):
                if status.get("provider") == "paddleocr":
                    page_result = self._extract_pil_image_text_with_paddle(image, status)
                    text = str(page_result.get("text") or "")
                else:
                    import pytesseract  # type: ignore

                    text = pytesseract.image_to_string(image, lang=self.language) or ""
                page_results.append({"page": index, "text": text})
            full_text = "\n\n".join(item["text"] for item in page_results if item.get("text"))
            return {"success": True, "text": full_text, "status": status, "pages": page_results, "error_message": None}
        except Exception as exc:
            return {"success": False, "text": "", "status": status, "pages": [], "error_message": f"PDF OCR 识别失败：{exc}"}

    def detect_scanned_pdf(self, path: str | Path) -> dict[str, Any]:
        try:
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            page_count = len(reader.pages)
            text = "\n".join((page.extract_text() or "").strip() for page in reader.pages[: min(page_count, 5)])
            return {
                "success": True,
                "page_count": page_count,
                "text_chars_preview": len(text),
                "ocr_recommended": page_count > 0 and len(text.strip()) < 20,
            }
        except Exception as exc:
            return {"success": False, "page_count": 0, "text_chars_preview": 0, "ocr_recommended": False, "error_message": str(exc)}

    def _parse_page_range(self, value: str | None, *, max_pages: int) -> list[int]:
        text = str(value or "").strip()
        if not text:
            return []
        pages: list[int] = []
        for part in text.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                left, right = part.split("-", 1)
                start = max(1, int(left.strip()))
                end = max(start, int(right.strip()))
                pages.extend(range(start, end + 1))
            else:
                pages.append(max(1, int(part)))
        result = []
        for page in pages:
            if page not in result:
                result.append(page)
            if len(result) >= max_pages:
                break
        return result

    def _extract_image_text_with_paddle(self, path: str | Path, status: dict[str, Any]) -> dict[str, Any]:
        try:
            from paddleocr import PaddleOCR  # type: ignore

            ocr = PaddleOCR(use_angle_cls=True, lang="ch" if "chi" in self.language else "en")
            result = ocr.ocr(str(path), cls=True)
            lines = []
            for page in result or []:
                for item in page or []:
                    if len(item) >= 2 and isinstance(item[1], (list, tuple)):
                        lines.append(str(item[1][0] or ""))
            text = "\n".join(line for line in lines if line.strip())
            return {"success": True, "text": text, "status": status, "error_message": None, "pages": [{"page": 1, "text": text}]}
        except Exception as exc:
            return {"success": False, "text": "", "status": status, "error_message": f"PaddleOCR 识别失败：{exc}"}

    def _extract_pil_image_text_with_paddle(self, image: Any, status: dict[str, Any]) -> dict[str, Any]:
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
            temp_path = Path(handle.name)
        try:
            image.save(temp_path)
            return self._extract_image_text_with_paddle(temp_path, status)
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass
