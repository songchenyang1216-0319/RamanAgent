"""综合 Raman 专业分析工具。"""

from __future__ import annotations

import json
from pathlib import Path

from backend.agent.tools.spectral_tools.baseline_quality_tool import analyze_baseline_quality
from backend.agent.tools.spectral_tools.peak_detection_tool import detect_peaks
from backend.agent.tools.spectral_tools.quality_tool import analyze_spectrum_quality
from backend.agent.tools.spectral_tools.similarity_tool import find_similar_history


def _safe_call(func, *args, **kwargs) -> dict:
    """调用子工具并把异常转成结构化结果。"""
    try:
        result = func(*args, **kwargs)
        if not isinstance(result, dict):
            return {"success": False, "error_message": "子工具返回结果不是字典。"}
        return result
    except Exception as exc:
        return {"success": False, "error_message": str(exc)}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _load_training_range() -> tuple[float | None, float | None]:
    """从模型登记信息读取训练浓度范围，不触碰模型权重。"""
    registry_path = _project_root() / "artifacts" / "model_registry.json"
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        current = registry.get("current_model_version") or registry.get("default_model")
        models = registry.get("models", [])
        if isinstance(models, dict):
            models = list(models.values())
        for model in models:
            if not current or model.get("model_version") == current:
                value = ((model.get("training_data") or {}).get("concentration_range") or [])[:2]
                if len(value) == 2:
                    return float(value[0]), float(value[1])
    except Exception:
        pass
    return None, None


def _extract_prediction_value(prediction_result: dict | None) -> float | None:
    prediction_result = prediction_result or {}
    for key in ("final_prediction", "fusion_prediction", "prediction", "methanol_concentration"):
        value = prediction_result.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None


def _analyze_ood_risk(prediction_result: dict | None, quality_analysis: dict, baseline_analysis: dict) -> dict:
    """轻量 OOD 风险提示：只用配置、预测值和已有置信度信号。"""
    prediction_result = prediction_result or {}
    train_min, train_max = _load_training_range()
    prediction = _extract_prediction_value(prediction_result)
    warnings = []
    factors = {}
    risk_score = 0.0

    if train_min is not None and train_max is not None:
        factors["training_concentration_range"] = [train_min, train_max]
        if prediction is not None:
            factors["prediction"] = prediction
            span = max(train_max - train_min, 1e-12)
            if prediction < train_min or prediction > train_max:
                distance = min(abs(prediction - train_min), abs(prediction - train_max)) / span
                risk_score += 0.45 + min(distance, 0.45)
                warnings.append("预测浓度超出训练浓度范围，属于训练分布外风险。")
            elif prediction < train_min + 0.03 * span or prediction > train_max - 0.03 * span:
                risk_score += 0.18
                warnings.append("预测浓度接近训练范围边界，建议谨慎解释。")
    else:
        factors["training_concentration_range"] = None

    confidence = prediction_result.get("confidence") or {}
    knn_distance = confidence.get("knn_distance") or confidence.get("distance")
    threshold = prediction_result.get("distance_threshold") or confidence.get("distance_threshold")
    if threshold is None:
        try:
            config = json.loads((_project_root() / "artifacts" / "config.json").read_text(encoding="utf-8"))
            threshold = config.get("distance_threshold")
        except Exception:
            threshold = None
    if knn_distance is not None and threshold:
        try:
            ratio = float(knn_distance) / max(float(threshold), 1e-12)
            factors["latent_distance_ratio"] = ratio
            if ratio > 1.5:
                risk_score += 0.35
                warnings.append("潜在特征距离明显高于训练参考阈值，可能与训练样本差异较大。")
            elif ratio > 1.0:
                risk_score += 0.20
                warnings.append("潜在特征距离略高于参考阈值，建议降低置信度。")
        except (TypeError, ValueError):
            pass

    if quality_analysis.get("success") and quality_analysis.get("overall_quality") == "poor":
        risk_score += 0.20
        warnings.append("光谱质量较差，会放大分布外和预测不稳定风险。")
    if baseline_analysis.get("success") and baseline_analysis.get("regression_suitability") != "suitable":
        risk_score += 0.15
        warnings.append("基线或预处理质量需要复核，回归预测可信度应下调。")

    factors["latent_reference_available"] = (_project_root() / "artifacts" / "latent_train.npy").exists()
    risk_score = min(float(risk_score), 1.0)
    if risk_score >= 0.55:
        level = "high"
    elif risk_score >= 0.25:
        level = "medium"
    else:
        level = "low"

    return {
        "level": level,
        "score": risk_score,
        "warnings": list(dict.fromkeys(warnings)),
        "factors": factors,
        "suggestion": "建议结合重复采集、历史样品和四阶段预处理图复核。" if level != "low" else "当前未发现明显训练分布外信号，但仍建议结合重复实验确认。",
    }


def _compose_professional_summary(key_findings: list[str], risks: list[str], suggestions: list[str], overall_level: str, ood_risk: dict) -> dict:
    if overall_level == "good":
        conclusion = "这条光谱整体可用于解释和回归预测，当前未见突出的质量风险。"
    elif overall_level == "acceptable":
        conclusion = "这条光谱可以作为参考，但部分质量或分布风险需要复核。"
    else:
        conclusion = "这条光谱存在较明显风险，预测结果不建议直接作为最终结论。"
    if ood_risk.get("level") == "high":
        conclusion = "预测存在较高训练分布外风险，应优先复核样品、光谱质量和模型适用范围。"
    elif ood_risk.get("level") == "medium" and overall_level == "good":
        conclusion = "光谱本身质量尚可，但模型适用范围存在一定不确定性。"

    return {
        "overall_level": overall_level,
        "conclusion": conclusion,
        "key_evidence": key_findings,
        "key_findings": key_findings,
        "risks": risks,
        "suggestions": list(dict.fromkeys(suggestions)),
        "ood_risk": ood_risk,
    }


def analyze_spectrum_professionally(csv_path: str | Path, prediction_result: dict | None = None) -> dict:
    """整合峰识别、质量评估、基线判断和历史相似样品比较。"""
    warnings = []
    peak_analysis = _safe_call(detect_peaks, csv_path)
    quality_analysis = _safe_call(analyze_spectrum_quality, csv_path)
    baseline_analysis = _safe_call(analyze_baseline_quality, csv_path, prediction_result)
    similarity_analysis = _safe_call(find_similar_history, prediction_result or {})

    for name, result in (
        ("峰识别", peak_analysis),
        ("光谱质量评估", quality_analysis),
        ("基线质量判断", baseline_analysis),
        ("历史相似样品比较", similarity_analysis),
    ):
        if not result.get("success"):
            warnings.append(f"{name}失败: {result.get('error_message') or result.get('message', '未知原因')}")

    key_findings = []
    risks = []
    suggestions = []

    if quality_analysis.get("success"):
        level = quality_analysis.get("overall_quality") or quality_analysis.get("quality_level")
        snr = (quality_analysis.get("metrics") or {}).get("estimated_snr")
        if level == "good":
            key_findings.append("光谱整体质量较好，信噪比和峰形可作为解释依据")
        elif level in {"acceptable", "medium"}:
            key_findings.append("光谱质量处于可接受范围")
        else:
            risks.append("光谱质量偏低，结果稳定性需要复核")
        if snr is not None:
            key_findings.append(f"估计信噪比约为 {float(snr):.2f}")
        for issue in quality_analysis.get("issues", []):
            risks.append(issue)
        suggestions.extend(quality_analysis.get("suggestions", []))

    if peak_analysis.get("success"):
        if peak_analysis.get("peak_count", 0) >= 3:
            key_findings.append("主要峰识别正常")
        else:
            risks.append("有效峰数量偏少")
        annotated_modes = []
        for peak in peak_analysis.get("peaks", [])[:3]:
            annotations = peak.get("knowledge_annotations") or []
            for annotation in annotations:
                if annotation.get("confidence") in {"possible", "caution"} and annotation.get("label") != "unassigned":
                    annotated_modes.append(f"{float(peak.get('wavenumber', 0.0)):.1f} cm^-1 附近可能对应 {annotation.get('label')}")
                    break
        if annotated_modes:
            key_findings.extend(annotated_modes[:3])
        suggestions.extend(peak_analysis.get("warnings", []))

    if baseline_analysis.get("success"):
        baseline_level = baseline_analysis.get("baseline_level")
        if baseline_level == "normal":
            key_findings.append("基线漂移不明显")
        else:
            risks.append("基线或预处理质量存在可疑风险")
        if baseline_analysis.get("negative_peak_risk"):
            risks.append("存在负峰风险，需要检查是否过度扣除基线")
        if baseline_analysis.get("peak_weakening_risk"):
            risks.append("峰形可能被预处理削弱")
        if baseline_analysis.get("regression_suitability") != "suitable":
            risks.append("处理后光谱用于回归预测时建议人工复核")
        suggestions.extend(baseline_analysis.get("suggestions", []))

    if similarity_analysis.get("success"):
        records = similarity_analysis.get("similar_records", [])
        if records:
            key_findings.append("已找到可参考的历史相似样品")
        else:
            key_findings.append("暂无可比较的历史样品")

    ood_risk = _analyze_ood_risk(prediction_result, quality_analysis, baseline_analysis)
    risks.extend(ood_risk.get("warnings", []))

    risk_count = len(risks) + len(warnings)
    if risk_count == 0:
        overall_level = "good"
    elif risk_count <= 2:
        overall_level = "acceptable"
    else:
        overall_level = "poor"
    if ood_risk.get("level") == "high":
        overall_level = "poor"
    elif ood_risk.get("level") == "medium" and overall_level == "good":
        overall_level = "acceptable"

    if not suggestions:
        suggestions.append("建议对同一样品进行重复采集以验证稳定性。")
    if ood_risk.get("level") != "low":
        suggestions.append(ood_risk.get("suggestion", "建议复核模型适用范围。"))

    return {
        "success": True,
        "peak_analysis": peak_analysis,
        "quality_analysis": quality_analysis,
        "baseline_analysis": baseline_analysis,
        "similarity_analysis": similarity_analysis,
        "ood_risk": ood_risk,
        "professional_summary": _compose_professional_summary(
            key_findings=key_findings,
            risks=list(dict.fromkeys(risks + warnings)),
            suggestions=suggestions,
            overall_level=overall_level,
            ood_risk=ood_risk,
        ),
        "warnings": warnings,
    }
