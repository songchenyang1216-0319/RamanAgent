from __future__ import annotations

from pathlib import Path

from backend.services.ocr import OCRService

from .base import BaseFileProcessor, ProcessedFile


class ImageFileProcessor(BaseFileProcessor):
    file_type = "image"
    supported_suffixes = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}

    def process(self, path: Path, *, file_id: str | None = None, **_: object) -> ProcessedFile:
        ocr_status = OCRService().get_status()
        metadata: dict[str, object] = {
            "suffix": path.suffix.lower(),
            "vision_required": True,
            "ocr_available": bool(ocr_status.get("available")),
            "ocr_status": ocr_status,
        }
        try:
            from PIL import Image

            with Image.open(path) as image:
                metadata.update({"width": image.width, "height": image.height, "mode": image.mode, "format": image.format})
        except ModuleNotFoundError:
            metadata["warning"] = "当前环境缺少 pillow，无法读取图片尺寸。"
        except Exception as exc:
            return self.failure(path, f"图片文件无法打开，可能已损坏：{exc}")
        return ProcessedFile(
            success=True,
            file_type=self.file_type,
            filename=path.name,
            summary="已识别为图片文件。图片内容理解需要支持视觉的模型或 image-understanding Skill。",
            metadata=metadata,
            preview="图片文件已登记，等待视觉模型或图片 Skill 处理。",
            chunks=[],
        )
