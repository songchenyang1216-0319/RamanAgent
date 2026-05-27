"""Raman 分析报告生成服务。"""

from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path
import re
import uuid

from backend.agent.tools.spectral_tools.spectrum_loader import load_raman_csv
from raman_core.methanol.config import PROJECT_ROOT, REPORT_DIR, ensure_dirs


def _sanitize_report_stem(sample_file: str) -> str:
    """将样品文件名转换为适合生成报告文件的安全名称。"""
    stem = Path(sample_file or "sample").stem
    safe_stem = re.sub(r"[^0-9A-Za-z._-]+", "_", stem).strip("._-")
    return safe_stem or "sample"


def _format_number(value, digits: int = 4) -> str:
    """将数值统一格式化。"""
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "未提供"


def _resolve_prediction(result: dict) -> float | None:
    for key in ("fusion_prediction", "final_prediction", "prediction"):
        value = result.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None


def _safe_relative_path(path_like: str | Path | None) -> str:
    """只返回项目内相对路径，避免把本机绝对路径写进报告。"""
    if not path_like:
        return "未提供"
    path = Path(str(path_like))
    try:
        if path.is_absolute():
            return str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
        return str(path).replace("\\", "/")
    except Exception:
        return path.name or "未提供"


def _sanitize_text(text: str | None) -> str:
    """屏蔽 API Key、绝对路径和堆栈痕迹。"""
    if not text:
        return ""
    value = str(text)
    value = re.sub(r"(?i)(api[_ -]?key|token)\s*[:=]\s*[A-Za-z0-9._\-]+", r"\1: [已隐藏]", value)
    value = re.sub(r"[A-Za-z]:\\[^\s]+", "[本机路径已隐藏]", value)
    value = re.sub(r"(/[^/\s]+)+", lambda match: "[路径已隐藏]" if len(match.group(0)) > 12 else match.group(0), value)
    value = re.sub(r"Traceback \(most recent call last\):[\s\S]*", "异常堆栈已隐藏。", value)
    return value.strip()


def _extract_spectrum_metadata(sample_path: str | None) -> dict:
    """尝试从 CSV 提取光谱点数和波数范围。"""
    if not sample_path:
        return {"points": "未提供", "wavenumber_range": "未提供"}
    loaded = load_raman_csv(sample_path)
    if not loaded.get("success"):
        return {"points": "未提供", "wavenumber_range": "未提供"}
    return {
        "points": int(loaded.get("points", 0)),
        "wavenumber_range": f"{_format_number(loaded.get('x_min'), 2)} - {_format_number(loaded.get('x_max'), 2)} cm^-1",
    }


def _prediction_tag(result: dict) -> str:
    prediction = _resolve_prediction(result)
    if prediction is None:
        return "pred_na"
    tag = f"{prediction:.3f}".replace(".", "_").replace("-", "m")
    return f"pred_{tag}"


def _report_id(sample_file: str, created_at: datetime, result: dict) -> str:
    timestamp = created_at.strftime("%Y%m%d_%H%M%S")
    stem = _sanitize_report_stem(sample_file)
    return f"{timestamp}_{stem}_{_prediction_tag(result)}_{uuid.uuid4().hex[:6]}"


def _normalize_figure_path(path_like: str | None) -> str:
    if not path_like:
        return ""
    relative = _safe_relative_path(path_like)
    if relative.startswith("outputs/figures/"):
        return relative.replace("outputs/figures/", "../figures/")
    return relative


def _build_sample_section(result: dict, model_info: dict, created_at: str) -> tuple[str, dict]:
    metadata = _extract_spectrum_metadata(result.get("sample_path"))
    lines = [
        "## 1. 样品信息",
        f"- 文件名：{result.get('sample_file') or '未提供'}",
        f"- 分析时间：{created_at}",
        f"- 模型版本：{model_info.get('model_version') or result.get('model_version') or '未提供'}",
        f"- 数据点数量：{metadata['points']}",
        f"- 波数范围：{metadata['wavenumber_range']}",
        "",
    ]
    return "\n".join(lines), metadata


def _build_prediction_section(result: dict, professional_analysis: dict, model_info: dict) -> str:
    confidence = result.get("confidence", {}) or {}
    disagreement = result.get("model_disagreement", {}) or {}
    ood_risk = professional_analysis.get("ood_risk", {}) or (professional_analysis.get("professional_summary", {}) or {}).get("ood_risk", {})
    train_warning = "是" if (ood_risk.get("level") in {"medium", "high"} and any("训练" in warning for warning in (ood_risk.get("warnings") or []))) else "否"
    unit = result.get("unit", "") or ""
    fusion_mode = ", ".join(model_info.get("algorithm", []) or ["SVR", "RF"])
    target_name = result.get("target_name") or result.get("prediction_target") or "甲醇浓度"
    return "\n".join(
        [
            "## 2. 预测结果",
            f"- 预测目标：{target_name}",
            f"- SVR 预测结果：{_format_number(result.get('svr_prediction'))} {unit}".rstrip(),
            f"- RF 预测结果：{_format_number(result.get('rf_prediction'))} {unit}".rstrip(),
            f"- 融合预测结果：{_format_number(_resolve_prediction(result))} {unit}".rstrip(),
            f"- 预测浓度：{_format_number(_resolve_prediction(result))} {unit}".rstrip(),
            f"- 置信度：{confidence.get('status') or '未提供'}",
            f"- 是否超出训练范围：{train_warning}",
            f"- 模型一致性说明：{disagreement.get('message') or '未提供'}",
            f"- 模型融合方式：{fusion_mode} 加权融合",
            "",
        ]
    )


def _build_pipeline_section(result: dict) -> str:
    pipeline = result.get("pipeline", []) or [
        "统一波数轴",
        "SG 平滑",
        "ALS 去基线",
        "CDAE 去噪",
        "CAE+ 基线估计",
        "标准化",
    ]
    normalized = []
    for step in pipeline:
        value = str(step)
        if value == "SVR/RF融合预测":
            normalized.append("SVR/RF 融合预测")
            continue
        normalized.append(value)
    if "标准化" not in normalized and "归一化" not in normalized:
        normalized.append("标准化")
    lines = ["## 3. 光谱预处理流程"]
    lines.extend(f"- {step}" for step in normalized)
    lines.append("")
    return "\n".join(lines)


def _build_quality_section(professional_analysis: dict) -> str:
    quality = professional_analysis.get("quality_analysis", {}) or {}
    quality_metrics = quality.get("metrics", {}) or {}
    baseline = professional_analysis.get("baseline_analysis", {}) or {}
    issues = quality.get("issues", []) or []
    clipping = quality.get("saturation_or_clipping_check", {}) or {}
    abnormal = quality.get("abnormal_intensity_check", {}) or {}
    lines = [
        "## 4. 光谱质量评价",
        f"- 总体质量：{quality.get('overall_quality') or quality.get('quality_level') or '未提供'}",
        f"- 噪声情况：估计信噪比 {_format_number(quality_metrics.get('estimated_snr'))}",
        f"- 基线漂移：{_format_number(quality_metrics.get('baseline_drift_score'))}",
        f"- 峰形保真度：{_format_number(quality_metrics.get('peak_sharpness_score'))}",
        f"- 异常点或饱和风险：{'存在提醒' if clipping.get('risk') or abnormal.get('risk') else '未见明显异常'}",
    ]
    if issues:
        lines.append(f"- 主要问题：{'；'.join(str(item) for item in issues[:4])}")
    baseline_warnings = baseline.get("warnings", []) or []
    if baseline_warnings:
        lines.append(f"- 基线补充说明：{'；'.join(str(item) for item in baseline_warnings[:3])}")
    lines.append("")
    return "\n".join(lines)


def _build_peak_section(professional_analysis: dict) -> str:
    peak_analysis = professional_analysis.get("peak_analysis", {}) or {}
    peaks = peak_analysis.get("peaks", []) if peak_analysis.get("success") else []
    lines = [
        "## 5. 特征峰与专业解释",
        "- 说明：以下解释仅反映常见 Raman 特征提示，不做过度确定的成分结论。",
    ]
    if peaks:
        for peak in peaks[:6]:
            annotation = next((item for item in (peak.get("knowledge_annotations") or []) if item.get("confidence") != "unknown"), None)
            description = annotation.get("possible_mode") if annotation else "当前峰位未命中内置提示区，建议结合全谱判断。"
            caution = annotation.get("caution") if annotation else "不做确定成分归属。"
            lines.append(
                f"- { _format_number(peak.get('wavenumber')) } cm^-1：强度 {_format_number(peak.get('intensity'))}，"
                f"可能解释为 {description} {caution}"
            )
    else:
        lines.append("- 当前未识别到足够清晰的主要峰位。")
    lines.append("")
    return "\n".join(lines)


def _build_history_section(professional_analysis: dict) -> str:
    similarity = professional_analysis.get("similarity_analysis", {}) or {}
    records = similarity.get("similar_records", []) if similarity.get("success") else []
    lines = ["## 6. 历史样品对比"]
    if records:
        for record in records[:5]:
            lines.append(
                f"- 相似样品：{record.get('sample_file') or '未命名样品'}，"
                f"预测值 {_format_number(record.get('final_prediction'))}，"
                f"差异 {_format_number(record.get('difference'))}，"
                f"时间 {record.get('created_at') or '未提供'}"
            )
        lines.append("- 差异说明：存在可参考的历史样品，但仍建议结合本次光谱质量和实验条件复核。")
        lines.append("- 是否需要复测：如当前风险项较多，建议复测。")
    else:
        lines.append(f"- 相似样品：{similarity.get('message') or '暂无可比较的历史样品'}")
        lines.append("- 差异说明：当前缺少足够接近的历史样品作横向对比。")
        lines.append("- 是否需要复测：若本次质量评价或 OOD 风险偏高，建议复测。")
    lines.append("")
    return "\n".join(lines)


def _build_conclusion_section(result: dict, professional_analysis: dict, llm_explanation: str) -> tuple[str, str]:
    summary = professional_analysis.get("professional_summary", {}) or {}
    risks = summary.get("risks", []) or []
    suggestions = summary.get("suggestions", []) or []
    prediction = _format_number(_resolve_prediction(result))
    unit = result.get("unit", "") or ""
    conclusion = summary.get("conclusion") or f"当前样品的融合预测浓度约为 {prediction} {unit}。"
    lines = [
        "## 7. 简要结论与建议",
        f"- 一句话结论：{conclusion}",
        f"- 风险提醒：{'；'.join(str(item) for item in risks[:4]) if risks else '当前未发现明显风险。'}",
        f"- 下一步实验建议：{'；'.join(str(item) for item in suggestions[:4]) if suggestions else '建议做重复采集并结合实验条件复核。'}",
        "",
    ]
    if llm_explanation:
        lines.extend(["## 附：解释摘要", llm_explanation, ""])
    return "\n".join(lines), conclusion


def _build_figure_section(figures: dict) -> tuple[str, list[dict]]:
    entries = []
    for key, value in (figures or {}).items():
        relative = _safe_relative_path(value)
        html_relative = _normalize_figure_path(value)
        if relative and relative != "未提供":
            entries.append({"key": key, "relative": relative, "html_relative": html_relative})
    lines = ["## 图谱与附件"]
    if entries:
        for item in entries:
            lines.append(f"- {item['key']}：{item['relative']}")
    else:
        lines.append("- 当前未生成图谱附件。")
    lines.append("")
    return "\n".join(lines), entries


def _build_html_report(markdown_sections: dict, report_title: str, figures: list[dict], created_at: str) -> str:
    figure_html = ""
    if figures:
        figure_cards = []
        for item in figures:
            if not item["html_relative"]:
                continue
            figure_cards.append(
                f"""
                <figure class="figure-card">
                  <img src="{escape(item['html_relative'])}" alt="{escape(item['key'])}">
                  <figcaption>{escape(item['key'])}</figcaption>
                </figure>
                """
            )
        if figure_cards:
            figure_html = f"<section><h2>图谱预览</h2><div class='figure-grid'>{''.join(figure_cards)}</div></section>"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{escape(report_title)}</title>
  <style>
    body {{
      margin: 0;
      font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
      background: #f4f7f6;
      color: #17212b;
    }}
    .page {{
      max-width: 1080px;
      margin: 0 auto;
      padding: 28px 20px 48px;
    }}
    .hero {{
      padding: 24px;
      border-radius: 16px;
      background: linear-gradient(135deg, #ffffff, #eef4f3);
      border: 1px solid #d8e1df;
      margin-bottom: 18px;
    }}
    .hero p {{
      margin: 6px 0 0;
      color: #667085;
    }}
    section {{
      margin-bottom: 14px;
      padding: 18px 20px;
      border-radius: 14px;
      background: #ffffff;
      border: 1px solid #d8e1df;
    }}
    h1, h2 {{
      margin-top: 0;
    }}
    ul {{
      margin: 0;
      padding-left: 20px;
      line-height: 1.8;
    }}
    .figure-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }}
    .figure-card {{
      margin: 0;
      padding: 10px;
      border-radius: 12px;
      background: #f7faf9;
      border: 1px solid #d8e1df;
    }}
    .figure-card img {{
      width: 100%;
      border-radius: 10px;
      background: #fff;
      border: 1px solid #d8e1df;
    }}
    .figure-card figcaption {{
      margin-top: 8px;
      color: #667085;
      text-align: center;
    }}
    .footer {{
      color: #667085;
      font-size: 13px;
    }}
  </style>
</head>
<body>
  <div class="page">
    <div class="hero">
      <h1>{escape(report_title)}</h1>
      <p>生成时间：{escape(created_at)}</p>
    </div>
    <section><pre style="white-space: pre-wrap; font: inherit; margin: 0;">{escape(markdown_sections["sample"])}</pre></section>
    <section><pre style="white-space: pre-wrap; font: inherit; margin: 0;">{escape(markdown_sections["prediction"])}</pre></section>
    <section><pre style="white-space: pre-wrap; font: inherit; margin: 0;">{escape(markdown_sections["pipeline"])}</pre></section>
    <section><pre style="white-space: pre-wrap; font: inherit; margin: 0;">{escape(markdown_sections["quality"])}</pre></section>
    <section><pre style="white-space: pre-wrap; font: inherit; margin: 0;">{escape(markdown_sections["peaks"])}</pre></section>
    <section><pre style="white-space: pre-wrap; font: inherit; margin: 0;">{escape(markdown_sections["history"])}</pre></section>
    <section><pre style="white-space: pre-wrap; font: inherit; margin: 0;">{escape(markdown_sections["conclusion"])}</pre></section>
    {figure_html}
    <p class="footer">本报告由 RamanAgent 自动生成，仅供实验分析参考。</p>
  </div>
</body>
</html>
"""


def generate_methanol_markdown_report(result: dict, llm_explanation: str | None = None) -> dict:
    """生成 Markdown 报告，并同步输出 HTML 版本。"""
    ensure_dirs()
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    created_at_dt = datetime.now()
    created_at = created_at_dt.strftime("%Y-%m-%d %H:%M:%S")
    sample_file = str(result.get("sample_file", "sample.csv"))
    report_id = _report_id(sample_file, created_at_dt, result)
    markdown_file = f"{report_id}.md"
    html_file = f"{report_id}.html"
    markdown_path = REPORT_DIR / markdown_file
    html_path = REPORT_DIR / html_file

    figures = result.get("figures", {}) or result.get("figure_paths", {}) or {}
    professional_analysis = result.get("professional_analysis", {}) or {}
    model_info = result.get("model_info", {}) or {}
    sanitized_explanation = _sanitize_text(llm_explanation or "未生成大模型解释。")

    sample_section, sample_meta = _build_sample_section(result, model_info, created_at)
    prediction_section = _build_prediction_section(result, professional_analysis, model_info)
    pipeline_section = _build_pipeline_section(result)
    quality_section = _build_quality_section(professional_analysis)
    peak_section = _build_peak_section(professional_analysis)
    history_section = _build_history_section(professional_analysis)
    conclusion_section, summary_text = _build_conclusion_section(result, professional_analysis, sanitized_explanation)
    figure_section, figure_entries = _build_figure_section(figures)

    report_title = "# RamanAgent 甲醇光谱分析报告"
    markdown_content = "\n".join(
        [
            report_title,
            "",
            sample_section,
            prediction_section,
            pipeline_section,
            quality_section,
            peak_section,
            history_section,
            conclusion_section,
            figure_section,
            "## 附注",
            "- 本报告由 RamanAgent 自动生成。",
            "- 报告中未写入 API Key、本机绝对路径或异常堆栈。",
            "- 专业解释仅用于辅助实验判断，不替代人工确认。",
            "",
        ]
    )
    markdown_path.write_text(markdown_content, encoding="utf-8")

    html_sections = {
        "sample": sample_section,
        "prediction": prediction_section,
        "pipeline": pipeline_section,
        "quality": quality_section,
        "peaks": peak_section,
        "history": history_section,
        "conclusion": conclusion_section,
    }
    html_content = _build_html_report(html_sections, "RamanAgent 甲醇光谱分析报告", figure_entries, created_at)
    html_path.write_text(html_content, encoding="utf-8")

    return {
        "report_id": report_id,
        "report_file": markdown_file,
        "report_path": f"outputs/reports/{markdown_file}",
        "report_markdown_file": markdown_file,
        "report_markdown_path": f"outputs/reports/{markdown_file}",
        "report_html_file": html_file,
        "report_html_path": f"outputs/reports/{html_file}",
        "created_at": created_at,
        "summary": summary_text,
        "formats": ["markdown", "html"],
        "spectrum_points": sample_meta.get("points"),
        "wavenumber_range": sample_meta.get("wavenumber_range"),
    }
