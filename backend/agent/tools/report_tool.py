"""报告与解释工具。"""

from __future__ import annotations

from typing import Any

from backend.services.llm_service import LLMService
from backend.services.report_service import generate_methanol_markdown_report


def _to_report_result(
    result: dict,
    professional_analysis: dict | None = None,
    model_info: dict | None = None,
    experiment_metadata: dict | None = None,
) -> dict:
    """将 Agent 标准结果转换为报告服务使用的字段格式。"""
    raw_result = (result or {}).get("raw_result")
    if isinstance(raw_result, dict) and raw_result:
        report_result = dict(raw_result)
        report_result["professional_analysis"] = professional_analysis or {}
        report_result["model_info"] = model_info or {}
        report_result["experiment_metadata"] = experiment_metadata or {}
        return report_result

    return {
        "sample_file": result.get("sample_file"),
        "sample_path": result.get("sample_path"),
        "svr_prediction": result.get("svr_prediction"),
        "rf_prediction": result.get("rf_prediction"),
        "fusion_prediction": result.get("final_prediction"),
        "unit": result.get("unit"),
        "confidence": result.get("confidence", {}) or {},
        "model_disagreement": result.get("model_disagreement", {}) or {},
        "figures": result.get("figure_paths", {}) or {},
        "pipeline": result.get("pipeline", []) or [],
        "professional_analysis": professional_analysis or {},
        "model_info": model_info or {},
        "experiment_metadata": experiment_metadata or {},
    }


def generate_report_tool(
    result: dict,
    llm_explanation: str | None = None,
    professional_analysis: dict | None = None,
    model_info: dict | None = None,
    experiment_metadata: dict | None = None,
) -> dict:
    """生成 Markdown 报告。"""
    report_result = _to_report_result(result, professional_analysis, model_info, experiment_metadata)
    if not report_result.get("fusion_prediction") and report_result.get("fusion_prediction") != 0:
        return {"success": False, "error_message": "预测结果无效，无法生成报告。"}

    try:
        report = generate_methanol_markdown_report(report_result, llm_explanation)
    except Exception as exc:
        return {"success": False, "error_message": f"报告生成失败: {exc}"}

    report_markdown = None
    report_path = report.get("report_path")
    if report_path:
        try:
            from raman_core.methanol.config import PROJECT_ROOT

            report_markdown = (PROJECT_ROOT / report_path).read_text(encoding="utf-8")
        except Exception:
            report_markdown = None

    return {
        "success": True,
        "report_id": report.get("report_id"),
        "created_at": report.get("created_at"),
        "summary": report.get("summary"),
        "formats": report.get("formats", []),
        "report_path": report.get("report_path"),
        "report_file": report.get("report_file"),
        "report_markdown_path": report.get("report_markdown_path"),
        "report_markdown_file": report.get("report_markdown_file"),
        "report_html_path": report.get("report_html_path"),
        "report_html_file": report.get("report_html_file"),
        "report_markdown": report_markdown,
    }


def explain_result_tool(
    result: dict,
    professional_analysis: dict | None = None,
    model_info: dict | None = None,
    experiment_metadata: dict | None = None,
) -> dict:
    """调用大模型解释工具，并提供降级说明。"""
    report_result = _to_report_result(result, professional_analysis, model_info, experiment_metadata)
    if report_result.get("fusion_prediction") is None or report_result.get("svr_prediction") is None or report_result.get("rf_prediction") is None:
        return {
            "success": False,
            "explanation": "预测结果无效，暂不生成大模型解释。",
            "error_message": "预测结果缺少关键预测值。",
        }

    explanation = LLMService().explain_methanol_result(report_result)
    unavailable_markers = (
        "未配置 SILICONFLOW_API_KEY",
        "未安装 openai 依赖",
        "大模型客户端未成功初始化",
        "大模型解释生成失败",
    )
    success = not any(marker in explanation for marker in unavailable_markers)
    if not success:
        disagreement = report_result.get("model_disagreement", {}) or {}
        model_info = report_result.get("model_info", {}) or {}
        absolute_difference = disagreement.get("absolute_difference")
        relative_difference = disagreement.get("relative_difference")
        rel_threshold = disagreement.get("rel_threshold")
        diff_text = "模型差异信息当前未提供。"
        if absolute_difference is not None and relative_difference is not None:
            diff_text = (
                f"SVR 与 RF 的绝对差异为 {float(absolute_difference):.4f}，"
                f"相对差异为 {float(relative_difference):.4f}。"
            )
            if rel_threshold is not None and float(relative_difference) <= float(rel_threshold):
                diff_text += " 当前相对差异低于阈值，模型一致性整体可接受。"
        fallback = (
            "大模型解释暂不可用，但预测流程已完成。"
            f" 当前模型版本为 {model_info.get('model_version', '未提供')}。"
            f" 当前融合预测值为 {float(report_result.get('fusion_prediction', 0.0)):.4f}{report_result.get('unit', '')}，"
            f" {diff_text}"
        )
        return {
            "success": False,
            "explanation": fallback,
            "structured_explanation": build_structured_prediction_explanation(
                report_result,
                professional_analysis=professional_analysis,
                model_info=model_info,
                experiment_metadata=experiment_metadata,
                explanation_text=fallback,
            ),
            "error_message": explanation,
        }
    return {
        "success": True,
        "explanation": explanation,
        "structured_explanation": build_structured_prediction_explanation(
            report_result,
            professional_analysis=professional_analysis,
            model_info=model_info,
            experiment_metadata=experiment_metadata,
            explanation_text=explanation,
        ),
        "error_message": None,
    }


def build_structured_prediction_explanation(
    result: dict[str, Any],
    professional_analysis: dict | None = None,
    model_info: dict | None = None,
    experiment_metadata: dict | None = None,
    explanation_text: str | None = None,
) -> dict[str, Any]:
    """把预测结果整理为前端易于渲染的结构化解释。"""
    professional_analysis = professional_analysis or {}
    model_info = model_info or {}
    experiment_metadata = experiment_metadata or {}
    confidence = result.get("confidence") or {}
    disagreement = result.get("model_disagreement") or {}
    quality = (professional_analysis.get("quality_analysis") or {}).get("metrics") or {}
    quality_level = (professional_analysis.get("quality_analysis") or {}).get("overall_quality") or "未提供"
    ood_risk = professional_analysis.get("ood_risk") or {}
    summary = professional_analysis.get("professional_summary") or {}
    peak_items = []
    for peak in ((professional_analysis.get("peak_analysis") or {}).get("peaks") or [])[:5]:
        label = "未标注"
        for annotation in peak.get("knowledge_annotations") or []:
            if annotation.get("label") and annotation.get("label") != "unassigned":
                label = str(annotation.get("label"))
                break
        peak_items.append(
            {
                "wavenumber": peak.get("wavenumber"),
                "intensity": peak.get("intensity"),
                "label": label,
            }
        )

    fusion_prediction = result.get("fusion_prediction")
    unit = result.get("unit", "")
    summary_lines = []
    if fusion_prediction is not None:
        summary_lines.append(f"本次预测浓度约为 {float(fusion_prediction):.4f}{unit}。")
    if summary.get("conclusion"):
        summary_lines.append(str(summary.get("conclusion")))
    if disagreement.get("message"):
        summary_lines.append(str(disagreement.get("message")))

    evidence_items = []
    if confidence.get("status"):
        evidence_items.append({"label": "置信度状态", "value": str(confidence.get("status"))})
    if confidence.get("knn_distance") is not None:
        evidence_items.append({"label": "KNN 距离", "value": f"{float(confidence.get('knn_distance')):.4f}"})
    if confidence.get("distance_threshold") is not None:
        evidence_items.append({"label": "距离阈值", "value": f"{float(confidence.get('distance_threshold')):.4f}"})
    if quality.get("estimated_snr") is not None:
        evidence_items.append({"label": "估计 SNR", "value": f"{float(quality.get('estimated_snr')):.2f}"})
    evidence_items.append({"label": "光谱质量", "value": str(quality_level)})
    if ood_risk.get("level"):
        evidence_items.append({"label": "分布外风险", "value": str(ood_risk.get("level"))})

    risks = list(summary.get("risks") or [])
    if disagreement.get("warning"):
        risks.append("SVR 与 RF 差异达到预警阈值，建议人工复核。")
    if not risks:
        risks.append("当前未发现明显高风险信号，但仍建议结合图谱人工复核。")

    suggestions = list(summary.get("suggestions") or [])
    if not suggestions:
        suggestions = [
            "建议结合原始光谱与预处理后图谱复核峰形是否稳定。",
            "如结果用于关键判断，建议补做重复采样或重复测试。",
        ]

    return {
        "summary": summary_lines,
        "model_comparison": {
            "fusion_prediction": fusion_prediction,
            "svr_prediction": result.get("svr_prediction"),
            "rf_prediction": result.get("rf_prediction"),
            "absolute_difference": disagreement.get("absolute_difference"),
            "relative_difference": disagreement.get("relative_difference"),
            "consistency_message": disagreement.get("message"),
        },
        "confidence_analysis": {
            "status": confidence.get("status"),
            "knn_distance": confidence.get("knn_distance"),
            "distance_threshold": confidence.get("distance_threshold"),
            "quality_level": quality_level,
            "ood_risk_level": ood_risk.get("level"),
            "ood_risk_score": ood_risk.get("score"),
            "evidence_items": evidence_items,
        },
        "spectral_features": peak_items,
        "risks": list(dict.fromkeys(risks)),
        "suggestions": list(dict.fromkeys(suggestions)),
        "experiment_metadata": experiment_metadata,
        "model_info": {
            "model_name": model_info.get("model_name"),
            "model_version": model_info.get("model_version"),
        },
        "explanation_text": explanation_text or "",
    }
