from __future__ import annotations

import base64
import io
import math
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from backend.core.model_registry import ModelRegistry
from backend.core.model_router import ModelRouter
from backend.services.llm_service import LLMService

from .base import BaseSkill, SkillResult


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
MAX_IMAGE_SIZE_BYTES = 20 * 1024 * 1024
OCR_KEYWORDS = ("提取文字", "识别文字", "ocr", "图片里的文字", "翻译图片", "看一下上面写了什么", "截图内容整理")
ERROR_SCREENSHOT_KEYWORDS = ("报错", "错误", "异常", "bug", "terminal", "powershell", "命令行", "控制台", "日志", "页面打不开", "黑屏", "接口失败")
RAMAN_KEYWORDS = ("raman", "拉曼", "sers", "光谱", "谱图", "峰位", "峰强", "基线", "荧光背景", "去噪", "归一化", "甲醇", "浓度", "预测", "光谱分类", "光谱回归")
CHART_KEYWORDS = ("figure", "论文图", "图表", "曲线", "坐标轴", "柱状图", "折线图", "散点图", "pca", "t-sne", "热图", "roc", "混淆矩阵")
SCREENSHOT_KEYWORDS = ("截图", "界面", "页面", "按钮", "前端", "后端", "ui", "布局", "窗口")


class ImageRouterSkill(BaseSkill):
    name = "image-router-skill"
    display_name = "图片路由与视觉分析"
    description = "自动识别上传图片类型，并根据图片内容与用户请求路由到 Raman 光谱图片分析、普通图片分析、截图分析、图表分析或 OCR 文字提取。"
    category = "视觉技能"
    requires_file = True
    supported_file_types = sorted(IMAGE_SUFFIXES)
    usage = "上传图片后，可自动分流到 Raman 光谱图、普通图片、截图、图表 Figure 或 OCR 文字提取。"
    skill_mode = "executable"

    def __init__(self) -> None:
        self._registry = ModelRegistry()
        self._model_router = ModelRouter(registry=self._registry)
        self.actions = [
            self._action("classify_image_type", "判断图片类型。"),
            self._action("analyze_raman_spectrum_image", "Raman / SERS / 光谱图像分析。"),
            self._action("analyze_general_image", "普通照片、普通图片内容分析。"),
            self._action("analyze_screenshot", "页面截图、软件界面、报错截图分析。"),
            self._action("analyze_chart_or_figure", "论文 Figure、图表、曲线图分析。"),
            self._action("ocr_extract_text", "图片文字提取、截图文字整理、图片翻译前置。"),
            self._action("image_quality_check", "图片基础质量检测，包括尺寸、格式、亮度、对比度、清晰度。"),
        ]

    def _action(self, name: str, description: str) -> dict[str, Any]:
        return {
            "name": name,
            "display_name": name,
            "description": description,
            "enabled": True,
            "available": True,
            "status": "ready",
            "unavailable_reason": "",
        }

    def run(self, **kwargs: Any) -> SkillResult:
        action_name = str(kwargs.get("action_name") or "classify_image_type")
        image_path = Path(str(kwargs.get("file_path") or "")).expanduser()
        message = str(kwargs.get("message") or kwargs.get("original_message") or "").strip()
        action_enabled_map = dict(kwargs.get("action_enabled_map") or {})

        if not image_path.exists():
            return self._failure_result(
                action_name=action_name,
                image_type="UNKNOWN_IMAGE",
                message="我没有找到这张图片文件，请重新上传后再试一次。",
                error="图片路径不存在。",
            )
        suffix = image_path.suffix.lower()
        if suffix not in IMAGE_SUFFIXES:
            return self._failure_result(
                action_name=action_name,
                image_type="UNKNOWN_IMAGE",
                message="我收到的文件不是当前 image-router-skill 支持的图片格式，请上传 PNG、JPG、WEBP、BMP 或 TIFF。",
                error="图片格式不支持。",
            )
        if image_path.stat().st_size > MAX_IMAGE_SIZE_BYTES:
            return self._failure_result(
                action_name=action_name,
                image_type="UNKNOWN_IMAGE",
                message="这张图片文件过大，当前先不建议直接分析。请压缩后重试，或裁剪出关键区域再上传。",
                error="图片体积过大。",
            )

        try:
            quality = self._quality_check(image_path)
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            return self._failure_result(
                action_name=action_name,
                image_type="UNKNOWN_IMAGE",
                message="我识别到这是图片扩展名，但文件内容无法正常读取，可能已经损坏或并不是真正的图片文件。",
                error=f"图片读取失败：{exc}",
            )

        if action_name == "image_quality_check":
            return self._quality_result(quality)

        classification = self._classify_request(message=message, filename=image_path.name, action_name=action_name)
        final_action = classification["action"]
        image_type = classification["image_type"]
        if final_action != "image_quality_check" and not action_enabled_map.get(final_action, True):
            return self._friendly_disabled_action_result(final_action, image_type, quality)

        context = self._resolve_model_context(
            provider_id=kwargs.get("provider_id"),
            model_id=kwargs.get("model_id"),
            user_id=kwargs.get("user_id"),
            conversation_id=kwargs.get("session_id"),
        )

        if final_action == "analyze_raman_spectrum_image":
            return self._run_raman_image_analysis(image_path, message, image_type, quality, context)
        if final_action == "analyze_screenshot":
            return self._run_screenshot_analysis(image_path, message, image_type, quality, context)
        if final_action == "analyze_chart_or_figure":
            return self._run_chart_analysis(image_path, message, image_type, quality, context)
        if final_action == "ocr_extract_text":
            return self._run_ocr_analysis(image_path, message, image_type, quality, context)
        if final_action == "analyze_general_image":
            return self._run_general_image_analysis(image_path, message, image_type, quality, context)
        return self._quality_result(quality, image_type=image_type)

    def _classify_request(self, *, message: str, filename: str, action_name: str) -> dict[str, str]:
        raw = str(message or "")
        text = raw.lower()
        file_text = str(filename or "").lower()
        if action_name and action_name != "classify_image_type":
            return {"action": action_name, "image_type": self._action_to_image_type(action_name)}
        if any(keyword in raw for keyword in OCR_KEYWORDS) or any(keyword in text for keyword in ("ocr",)):
            return {"action": "ocr_extract_text", "image_type": "TEXT_IMAGE"}
        if any(keyword in raw for keyword in ERROR_SCREENSHOT_KEYWORDS) or any(keyword in file_text for keyword in ("error", "terminal", "console", "powershell")):
            return {"action": "analyze_screenshot", "image_type": "ERROR_SCREENSHOT"}
        if any(keyword in raw for keyword in RAMAN_KEYWORDS) or any(keyword in file_text for keyword in ("raman", "sers", "spectrum", "spectra", "peak")):
            return {"action": "analyze_raman_spectrum_image", "image_type": "RAMAN_SPECTRUM_IMAGE"}
        if any(keyword in raw for keyword in CHART_KEYWORDS) or any(keyword in file_text for keyword in ("figure", "chart", "plot", "curve", "graph", "pca", "roc")):
            return {"action": "analyze_chart_or_figure", "image_type": "CHART_OR_FIGURE"}
        if any(keyword in raw for keyword in SCREENSHOT_KEYWORDS) or any(keyword in file_text for keyword in ("screenshot", "screen", "snip", "capture", "ui")):
            return {"action": "analyze_screenshot", "image_type": "SCREENSHOT"}
        return {"action": "analyze_general_image", "image_type": "GENERAL_PHOTO"}

    def _action_to_image_type(self, action_name: str) -> str:
        mapping = {
            "analyze_raman_spectrum_image": "RAMAN_SPECTRUM_IMAGE",
            "analyze_general_image": "GENERAL_PHOTO",
            "analyze_screenshot": "SCREENSHOT",
            "analyze_chart_or_figure": "CHART_OR_FIGURE",
            "ocr_extract_text": "TEXT_IMAGE",
            "image_quality_check": "UNKNOWN_IMAGE",
            "classify_image_type": "UNKNOWN_IMAGE",
        }
        return mapping.get(action_name, "UNKNOWN_IMAGE")

    def _resolve_model_context(
        self,
        *,
        provider_id: str | None,
        model_id: str | None,
        user_id: str | None,
        conversation_id: str | None,
    ) -> dict[str, Any]:
        self._registry.reload()
        selection = self._model_router.resolve_selection(
            provider_id=provider_id,
            model_id=model_id,
            user_id=user_id,
            conversation_id=conversation_id,
        )
        current_model = {
            "provider_id": selection.get("provider_id"),
            "provider_name": selection.get("provider_name"),
            "model_id": selection.get("model_id"),
            "model_name": selection.get("model_name"),
            "supports_vision": bool(selection.get("supports_vision")),
        }
        available_vision_models = self._registry.list_available_vision_models()
        return {
            "current_model": current_model,
            "available_vision_models": available_vision_models,
        }

    def _quality_check(self, image_path: Path) -> dict[str, Any]:
        with Image.open(image_path) as image:
            image.load()
            grayscale = ImageOps.grayscale(image)
            array = np.asarray(grayscale, dtype=np.float32)
            brightness = float(array.mean()) if array.size else 0.0
            contrast = float(array.std()) if array.size else 0.0
            diff_x = np.abs(np.diff(array, axis=1)) if array.shape[1] > 1 else np.zeros_like(array)
            diff_y = np.abs(np.diff(array, axis=0)) if array.shape[0] > 1 else np.zeros_like(array)
            sharpness = float(math.sqrt(float((diff_x.mean() if diff_x.size else 0.0) ** 2 + (diff_y.mean() if diff_y.size else 0.0) ** 2)))
            warnings: list[str] = []
            if brightness < 45:
                warnings.append("图片疑似过暗")
            if brightness > 215:
                warnings.append("图片疑似过亮")
            if contrast < 18:
                warnings.append("图片整体对比度偏低")
            if sharpness < 12:
                warnings.append("图片疑似模糊")
            return {
                "filename": image_path.name,
                "format": str(image.format or image_path.suffix.lstrip(".").upper() or "UNKNOWN"),
                "width": int(image.width),
                "height": int(image.height),
                "file_size_bytes": int(image_path.stat().st_size),
                "mode": str(image.mode or ""),
                "brightness": round(brightness, 2),
                "contrast": round(contrast, 2),
                "sharpness": round(sharpness, 2),
                "warnings": warnings,
            }

    def _quality_result(self, quality: dict[str, Any], image_type: str = "UNKNOWN_IMAGE") -> SkillResult:
        warnings = list(quality.get("warnings") or [])
        impact = "；".join(warnings) if warnings else "当前图片尺寸和基础质量看起来可以继续用于后续分析。"
        analysis_markdown = (
            "## 图片基础质量检测\n"
            f"- 文件名：{quality.get('filename')}\n"
            f"- 格式：{quality.get('format')}\n"
            f"- 分辨率：{quality.get('width')} × {quality.get('height')}\n"
            f"- 文件大小：{quality.get('file_size_bytes')} bytes\n"
            f"- 色彩模式：{quality.get('mode')}\n"
            f"- 亮度估计：{quality.get('brightness')}\n"
            f"- 对比度估计：{quality.get('contrast')}\n"
            f"- 清晰度估计：{quality.get('sharpness')}\n"
            f"- 影响判断：{impact}\n"
        )
        return SkillResult(
            success=True,
            skill_name=self.name,
            action_name="image_quality_check",
            summary="已完成图片基础质量检测。",
            data={
                "skill": self.name,
                "action": "image_quality_check",
                "image_type": image_type,
                "summary": "已完成图片基础质量检测。",
                "analysis_markdown": analysis_markdown,
                "quality": quality,
                "limitations": [],
                "next_steps": ["如果需要理解图片内容，请切换到支持视觉的模型后重试。"],
                "tool_info": self._tool_info("image_quality_check", image_type, quality.get("filename"), True, None),
            },
        )

    def _friendly_disabled_action_result(self, action_name: str, image_type: str, quality: dict[str, Any]) -> SkillResult:
        message = f"当前图片已识别到需要调用 `{action_name}`，但这个子能力目前被禁用了。你可以先在 Skill 管理页面重新启用它。"
        return SkillResult(
            success=False,
            skill_name=self.name,
            action_name=action_name,
            summary=message,
            data={
                "skill": self.name,
                "action": action_name,
                "image_type": image_type,
                "summary": message,
                "analysis_markdown": message,
                "quality": quality,
                "limitations": ["对应子能力当前已禁用。"],
                "next_steps": [f"在 Skill 管理页面启用 {action_name}。"],
                "tool_info": self._tool_info(action_name, image_type, quality.get("filename"), False, message),
            },
            errors=[message],
        )

    def _failure_result(self, *, action_name: str, image_type: str, message: str, error: str) -> SkillResult:
        return SkillResult(
            success=False,
            skill_name=self.name,
            action_name=action_name,
            summary=message,
            data={
                "skill": self.name,
                "action": action_name,
                "image_type": image_type,
                "analysis_markdown": message,
                "error": message,
                "tool_info": self._tool_info(action_name, image_type, None, False, message),
            },
            errors=[error],
        )

    def _tool_info(self, action: str, image_type: str, filename: str | None, success: bool, error: str | None) -> dict[str, Any]:
        return {
            "source": "skill_execution",
            "skill": self.name,
            "action": action,
            "image_type": image_type,
            "success": bool(success),
            "filename": filename or "",
            "error": error or "",
            "mode": "image_router",
        }

    def _degrade_without_vision(
        self,
        *,
        action_name: str,
        image_type: str,
        quality: dict[str, Any],
        model_context: dict[str, Any],
        message: str,
        limitations: list[str],
        next_steps: list[str],
    ) -> SkillResult:
        current_model = model_context.get("current_model") or {}
        available_vision_models = list(model_context.get("available_vision_models") or [])
        if current_model.get("supports_vision"):
            degrade_title = "视觉模型调用失败，我先给出图片质量检测结果。"
        elif available_vision_models:
            model_names = "、".join(item.get("display_name") or item.get("model_id") or "" for item in available_vision_models[:4])
            degrade_title = (
                "当前模型不支持视觉理解，请切换到支持视觉的模型后重试。"
                f"系统检测到可用视觉模型：{model_names}。"
            )
        else:
            degrade_title = (
                "当前没有可用视觉模型，无法可靠理解图片内容。"
                "我已先完成图片基础质量检测。若需要内容分析，请配置或切换到支持视觉的模型。"
            )
        analysis_markdown = (
            f"{degrade_title}\n\n"
            "## 图片基础质量检测\n"
            f"- 文件名：{quality.get('filename')}\n"
            f"- 格式：{quality.get('format')}\n"
            f"- 分辨率：{quality.get('width')} × {quality.get('height')}\n"
            f"- 亮度：{quality.get('brightness')}\n"
            f"- 对比度：{quality.get('contrast')}\n"
            f"- 清晰度：{quality.get('sharpness')}\n"
            f"- 质量提醒：{'；'.join(quality.get('warnings') or ['未发现明显基础质量风险'])}\n\n"
            f"{message}"
        )
        return SkillResult(
            success=True,
            skill_name=self.name,
            action_name=action_name,
            summary=degrade_title,
            data={
                "skill": self.name,
                "action": action_name,
                "image_type": image_type,
                "summary": degrade_title,
                "analysis_markdown": analysis_markdown,
                "quality": quality,
                "limitations": limitations,
                "next_steps": next_steps,
                "tool_info": self._tool_info(action_name, image_type, quality.get("filename"), True, None),
            },
        )

    def _call_vision_model(self, image_path: Path, prompt: str, model_context: dict[str, Any]) -> str:
        current_model = model_context.get("current_model") or {}
        if not current_model.get("supports_vision"):
            raise RuntimeError("CURRENT_MODEL_NOT_VISION")
        llm = LLMService(provider_id=current_model.get("provider_id"), model_id=current_model.get("model_id"))
        if llm.client is None:
            raise RuntimeError("VISION_CLIENT_NOT_READY")
        mime = self._mime_type(image_path.suffix.lower())
        with Image.open(image_path) as image:
            image.load()
            buffer = io.BytesIO()
            image.save(buffer, format=image.format or "PNG")
            image_bytes = buffer.getvalue()
        image_data_url = f"data:{mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"
        response, _ = llm.model_router.chat(
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_data_url}},
                    ],
                }
            ],
            provider_id=current_model.get("provider_id"),
            model_id=current_model.get("model_id"),
            stream=False,
            temperature=0.2,
            max_tokens=1200,
            timeout_seconds=90,
        )
        return str(response.choices[0].message.content if response.choices else "").strip()

    def _mime_type(self, suffix: str) -> str:
        return {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
            ".tif": "image/tiff",
            ".tiff": "image/tiff",
        }.get(suffix.lower(), "image/png")

    def _run_raman_image_analysis(
        self,
        image_path: Path,
        message: str,
        image_type: str,
        quality: dict[str, Any],
        model_context: dict[str, Any],
    ) -> SkillResult:
        limitations = [
            "仅根据图片无法进行严格的峰位计算、基线校正、浓度预测或定量建模。",
            "如需精确分析，请上传原始光谱 CSV / TXT 数据。",
        ]
        next_steps = [
            "上传原始 Raman CSV / TXT。",
            "做 SG 平滑、ALS 基线校正、归一化。",
            "做峰识别、浓度预测或生成 Raman 分析报告。",
        ]
        prompt = (
            "你是一名 Raman / SERS 光谱分析助手。请只基于图片中能看到的内容做谨慎判断，"
            "不要把图片当原始光谱数据。请用中文输出：1. 图片类型判断；2. 坐标轴、峰、基线、噪声、荧光背景、多曲线、图例；"
            "3. Raman 专业解释；4. 适合汇报/论文的判断；5. 明确提醒仅凭图片不能做严格峰位和定量分析。"
            f"\n用户要求：{message or '请分析这张 Raman 光谱图片'}"
        )
        try:
            vision_text = self._call_vision_model(image_path, prompt, model_context)
        except Exception:
            return self._degrade_without_vision(
                action_name="analyze_raman_spectrum_image",
                image_type=image_type,
                quality=quality,
                model_context=model_context,
                message="根据你的提问，这张图会按 Raman 光谱图片流程处理，但当前还不能可靠确认峰位、坐标轴和基线细节。",
                limitations=limitations,
                next_steps=next_steps,
            )
        analysis_markdown = (
            "## Raman 图片判断\n"
            "这张图疑似 Raman 光谱图 / SERS 光谱图 / 光谱曲线图。\n\n"
            f"{vision_text}\n\n"
            "## 限制说明\n"
            "仅根据图片无法进行严格的峰位计算、基线校正、浓度预测或定量建模。如需精确分析，请上传原始光谱 CSV / TXT 数据。\n\n"
            "## 后续建议\n"
            "- 上传原始 Raman CSV / TXT\n"
            "- 做 SG 平滑、ALS 基线校正、归一化\n"
            "- 做峰识别、浓度预测、生成 Raman 分析报告\n"
        )
        return self._success_result("analyze_raman_spectrum_image", image_type, quality, analysis_markdown, limitations, next_steps)

    def _run_general_image_analysis(
        self,
        image_path: Path,
        message: str,
        image_type: str,
        quality: dict[str, Any],
        model_context: dict[str, Any],
    ) -> SkillResult:
        limitations = ["普通图片分析依赖视觉模型识别，当前结果应结合原图人工复核。"]
        next_steps = ["如果需要更细粒度说明，可以补充你最关心的区域或问题。"]
        prompt = (
            "请用中文分析这张普通图片，输出：1. 图片内容概述；2. 主要对象/场景；3. 对用户问题的回答；4. 需要注意的细节；5. 后续建议。"
            f"\n用户要求：{message or '帮我看看这张图片主要是什么内容。'}"
        )
        try:
            vision_text = self._call_vision_model(image_path, prompt, model_context)
        except Exception:
            return self._degrade_without_vision(
                action_name="analyze_general_image",
                image_type=image_type,
                quality=quality,
                model_context=model_context,
                message="当前无法可靠理解图片内容，因此没有强行给出对象或场景判断。",
                limitations=["当前无法可靠理解图片内容。"],
                next_steps=["请切换到支持视觉理解的模型后重试。"],
            )
        return self._success_result("analyze_general_image", image_type, quality, vision_text, limitations, next_steps)

    def _run_screenshot_analysis(
        self,
        image_path: Path,
        message: str,
        image_type: str,
        quality: dict[str, Any],
        model_context: dict[str, Any],
    ) -> SkillResult:
        limitations = ["截图中的小字、日志细节可能无法百分之百识别完整。"]
        next_steps = ["如果日志太小，建议裁剪报错区域后再发一次。", "如果方便，也可以直接粘贴报错文本。"]
        prompt = (
            "请把这张截图按开发排障场景分析。输出：1. 这是什么界面；2. 能看清的报错或提示；3. 可能原因；4. 排查步骤；5. 可复制命令；6. 还需要用户补充什么。"
            "如果文字看不清，要明确说明“截图文字较小，可能识别不完整”。不要编造不存在的错误日志。"
            f"\n用户要求：{message or '帮我分析这张截图。'}"
        )
        try:
            vision_text = self._call_vision_model(image_path, prompt, model_context)
        except Exception:
            return self._degrade_without_vision(
                action_name="analyze_screenshot",
                image_type=image_type,
                quality=quality,
                model_context=model_context,
                message="当前没有可靠的视觉理解能力，所以还不能稳妥读取截图中的界面和报错文字。",
                limitations=limitations,
                next_steps=next_steps,
            )
        return self._success_result("analyze_screenshot", image_type, quality, vision_text, limitations, next_steps)

    def _run_chart_analysis(
        self,
        image_path: Path,
        message: str,
        image_type: str,
        quality: dict[str, Any],
        model_context: dict[str, Any],
    ) -> SkillResult:
        limitations = ["如果图中文字、图例或坐标轴过小，解释可能不完整。"]
        next_steps = ["如果这是论文图，建议补充图注或上下文段落。", "如果图像很复杂，可以裁剪关键子图分别分析。"]
        prompt = (
            "请用中文分析这张论文 Figure / 图表。输出：1. 图想说明什么；2. 横轴和纵轴；3. 每条曲线/颜色/分组代表什么；4. 关键趋势；5. 作者可能结论；6. 组会怎么讲；7. 老师可能追问什么。"
            "如果图表看起来像 Raman 光谱图，要加入 Raman 专业解释并明确说明。"
            f"\n用户要求：{message or '帮我解释这张图。'}"
        )
        try:
            vision_text = self._call_vision_model(image_path, prompt, model_context)
        except Exception:
            return self._degrade_without_vision(
                action_name="analyze_chart_or_figure",
                image_type=image_type,
                quality=quality,
                model_context=model_context,
                message="当前没有视觉模型，因此无法可靠读取图中的坐标轴、图例和趋势。",
                limitations=limitations,
                next_steps=next_steps,
            )
        return self._success_result("analyze_chart_or_figure", image_type, quality, vision_text, limitations, next_steps)

    def _run_ocr_analysis(
        self,
        image_path: Path,
        message: str,
        image_type: str,
        quality: dict[str, Any],
        model_context: dict[str, Any],
    ) -> SkillResult:
        limitations = ["图片文字识别结果可能存在缺字、错字或段落错位，需要人工复核。"]
        next_steps = ["如果图片里文字很多，建议裁剪关键区域后再识别。"]
        prompt = (
            "请先识别图片中的文字，再按段落整理输出。"
            "如果用户要求翻译，请把原文和中文翻译都给出；看不清的位置请标注“可能识别不完整”。"
            f"\n用户要求：{message or '请提取图片文字。'}"
        )
        try:
            vision_text = self._call_vision_model(image_path, prompt, model_context)
        except Exception:
            current_model = model_context.get("current_model") or {}
            available_vision_models = list(model_context.get("available_vision_models") or [])
            if not current_model.get("supports_vision") and not available_vision_models:
                message_text = "当前没有可用视觉模型或 OCR 引擎，无法可靠提取图片文字。"
            else:
                message_text = "当前没有可用的视觉识别结果，无法可靠提取图片文字。"
            return self._degrade_without_vision(
                action_name="ocr_extract_text",
                image_type=image_type,
                quality=quality,
                model_context=model_context,
                message=message_text,
                limitations=limitations,
                next_steps=["请切换到支持视觉的模型后重试。"],
            )
        return self._success_result("ocr_extract_text", image_type, quality, vision_text, limitations, next_steps)

    def _success_result(
        self,
        action_name: str,
        image_type: str,
        quality: dict[str, Any],
        analysis_markdown: str,
        limitations: list[str],
        next_steps: list[str],
    ) -> SkillResult:
        summary = str(analysis_markdown or "").strip().splitlines()[0] if analysis_markdown else "图片分析完成。"
        return SkillResult(
            success=True,
            skill_name=self.name,
            action_name=action_name,
            summary=summary,
            data={
                "skill": self.name,
                "action": action_name,
                "image_type": image_type,
                "summary": summary,
                "analysis_markdown": analysis_markdown,
                "quality": quality,
                "limitations": limitations,
                "next_steps": next_steps,
                "tool_info": self._tool_info(action_name, image_type, quality.get("filename"), True, None),
            },
        )
