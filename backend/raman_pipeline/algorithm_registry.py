"""Algorithm registry for composable Raman pipelines."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from raman_core.methanol.config import ARTIFACT_DIR

from .algorithm_schema import AlgorithmCallable, AlgorithmSpec
from . import classical_ml, deep_learning, feature_extraction, postprocessing, preprocessing, spectrum_io


class AlgorithmRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, AlgorithmSpec] = {}
        self._handlers: dict[str, AlgorithmCallable] = {}

    def register(self, spec: AlgorithmSpec, handler: AlgorithmCallable) -> None:
        if spec.algorithm_id in self._specs:
            raise ValueError(f"重复的 algorithm_id: {spec.algorithm_id}")
        self._specs[spec.algorithm_id] = spec
        self._handlers[spec.algorithm_id] = handler

    def list(self) -> list[AlgorithmSpec]:
        return list(self._specs.values())

    def get(self, algorithm_id: str) -> AlgorithmSpec | None:
        return self._specs.get(str(algorithm_id))

    def handler(self, algorithm_id: str) -> AlgorithmCallable:
        return self._handlers[str(algorithm_id)]

    def to_dict(self) -> dict[str, Any]:
        items = [spec.to_dict() for spec in self.list()]
        return {
            "total": len(items),
            "available_count": sum(1 for item in items if item.get("available")),
            "unavailable_count": sum(1 for item in items if not item.get("available")),
            "algorithms": items,
        }


def _schema(**properties: Any) -> dict[str, Any]:
    return {"type": "object", "properties": properties}


def _number(default: float | int, description: str = "") -> dict[str, Any]:
    return {"type": "number", "default": default, "description": description}


def _integer(default: int, description: str = "") -> dict[str, Any]:
    return {"type": "integer", "default": default, "description": description}


def _boolean(default: bool, description: str = "") -> dict[str, Any]:
    return {"type": "boolean", "default": default, "description": description}


def _array(description: str = "") -> dict[str, Any]:
    return {"type": "array", "description": description}


def _dl_unavailable_reason(model_file: str | None) -> str:
    if not model_file:
        return "深度学习模型文件未配置；该算法当前仅作为 Pipeline 占位登记，不能执行。"
    path = ARTIFACT_DIR / model_file
    if not path.exists():
        return f"深度学习模型文件缺失：{path}。请先训练或配置模型文件后再启用该算法。"
    return "深度学习模型文件存在，但新 Raman Pipeline 尚未接入该占位算法的推理适配器，当前不可执行。"


def _register(
    registry: AlgorithmRegistry,
    algorithm_id: str,
    display_name: str,
    category: str,
    description: str,
    handler: AlgorithmCallable,
    *,
    input_type: str = "spectrum",
    output_type: str = "spectrum",
    default_params: dict[str, Any] | None = None,
    param_schema: dict[str, Any] | None = None,
    requires_model_file: bool = False,
    model_file_key: str | None = None,
    available: bool = True,
    unavailable_reason: str = "",
    tags: list[str] | None = None,
) -> None:
    registry.register(
        AlgorithmSpec(
            algorithm_id=algorithm_id,
            display_name=display_name,
            category=category,
            description=description,
            input_type=input_type,
            output_type=output_type,
            default_params=default_params or {},
            param_schema=param_schema or _schema(),
            requires_model_file=requires_model_file,
            model_file_key=model_file_key,
            available=available,
            unavailable_reason=unavailable_reason,
            tags=tags or [],
        ),
        handler,
    )


def build_registry() -> AlgorithmRegistry:
    registry = AlgorithmRegistry()

    _register(
        registry,
        "load_csv_spectrum",
        "读取 CSV 光谱",
        "读取校验",
        "读取 CSV 并推断波数/强度列。",
        spectrum_io.load_csv_spectrum,
        input_type="file",
        default_params={},
        param_schema=_schema(wavenumber_column={"type": "string"}, intensity_column={"type": "string"}),
        tags=["csv", "io"],
    )
    _register(registry, "validate_spectrum_csv", "校验光谱 CSV", "读取校验", "校验光谱点数、数值长度和 NaN/Inf。", spectrum_io.validate_spectrum_csv, output_type="validation", tags=["csv"])
    _register(registry, "infer_wavenumber_intensity_columns", "推断波数/强度列", "读取校验", "根据列名和数值列自动推断波数列与强度列。", spectrum_io.infer_wavenumber_intensity_columns, output_type="metadata", tags=["csv"])
    _register(registry, "remove_nan_inf", "移除 NaN/Inf", "读取校验", "移除波数或强度中的 NaN/Inf 点。", preprocessing.remove_nan_inf, tags=["clean"])
    _register(registry, "sort_by_wavenumber", "按波数排序", "读取校验", "按波数从小到大排序。", preprocessing.sort_by_wavenumber, tags=["clean"])
    _register(registry, "remove_duplicate_wavenumber", "合并重复波数", "读取校验", "对重复波数的强度取平均。", preprocessing.remove_duplicate_wavenumber, tags=["clean"])
    _register(
        registry,
        "crop_wavenumber_range",
        "裁剪波数范围",
        "读取校验",
        "保留指定波数范围内的数据点。",
        preprocessing.crop_wavenumber_range,
        default_params={"min_wavenumber": 400, "max_wavenumber": 1800},
        param_schema=_schema(min_wavenumber=_number(400), max_wavenumber=_number(1800)),
        tags=["crop"],
    )

    _register(
        registry,
        "resample_linear",
        "线性重采样",
        "波数轴",
        "将光谱线性插值到目标波数轴。",
        preprocessing.resample_linear,
        default_params={"points": 1024},
        param_schema=_schema(start=_number(400), end=_number(1800), points=_integer(1024), target_axis=_array("可选目标波数轴")),
        tags=["axis", "interpolation"],
    )
    _register(registry, "resample_cubic", "三次重采样", "波数轴", "将光谱三次插值到目标波数轴。", preprocessing.resample_cubic, default_params={"points": 1024}, param_schema=_schema(start=_number(400), end=_number(1800), points=_integer(1024), target_axis=_array("可选目标波数轴")), tags=["axis", "interpolation"])
    _register(registry, "align_to_reference_axis", "对齐参考波数轴", "波数轴", "按 reference_axis 对齐光谱。", preprocessing.align_to_reference_axis, default_params={}, param_schema=_schema(reference_axis=_array("参考波数轴")), tags=["axis"])

    _register(registry, "savitzky_golay", "Savitzky-Golay 平滑", "平滑", "使用 SG 滤波平滑强度曲线。", preprocessing.savitzky_golay, default_params={"window_length": 11, "polyorder": 2}, param_schema=_schema(window_length=_integer(11), polyorder=_integer(2)), tags=["smooth"])
    _register(registry, "moving_average", "移动平均", "平滑", "使用移动平均平滑强度曲线。", preprocessing.moving_average, default_params={"window_size": 5}, param_schema=_schema(window_size=_integer(5)), tags=["smooth"])
    _register(registry, "gaussian_filter", "高斯滤波", "平滑", "使用一维高斯滤波平滑强度曲线。", preprocessing.gaussian_filter, default_params={"sigma": 1.0}, param_schema=_schema(sigma=_number(1.0)), tags=["smooth"])
    _register(registry, "median_filter", "中值滤波", "平滑", "使用中值滤波抑制尖峰噪声。", preprocessing.median_filter, default_params={"size": 5}, param_schema=_schema(size=_integer(5)), tags=["smooth"])
    _register(registry, "butterworth_lowpass", "Butterworth 低通", "平滑", "使用 Butterworth 低通滤波。", preprocessing.butterworth_lowpass, default_params={"cutoff": 0.08, "order": 3}, param_schema=_schema(cutoff=_number(0.08), order=_integer(3)), tags=["smooth"])

    _register(registry, "polynomial_baseline", "多项式基线", "基线", "拟合多项式基线。", preprocessing.polynomial_baseline, default_params={"degree": 3}, param_schema=_schema(degree=_integer(3)), output_type="baseline", tags=["baseline"])
    _register(registry, "rubberband_baseline", "Rubberband 基线", "基线", "使用凸包近似估计橡皮筋基线。", preprocessing.rubberband_baseline, output_type="baseline", tags=["baseline"])
    _register(registry, "als_baseline", "ALS 基线", "基线", "使用 Asymmetric Least Squares 估计基线。", preprocessing.als_baseline, default_params={"lam": 100000.0, "p": 0.01, "iterations": 10}, param_schema=_schema(lam=_number(100000.0), p=_number(0.01), iterations=_integer(10)), output_type="baseline", tags=["baseline"])
    _register(registry, "airpls_baseline", "airPLS 基线", "基线", "使用 airPLS 风格参数估计基线。", preprocessing.airpls_baseline, default_params={"lam": 100000.0, "iterations": 12}, param_schema=_schema(lam=_number(100000.0), iterations=_integer(12)), output_type="baseline", tags=["baseline"])
    _register(registry, "baseline_subtraction", "基线扣除", "基线", "从当前强度中扣除已估计基线。", preprocessing.baseline_subtraction, default_params={"clip_negative": False}, param_schema=_schema(clip_negative=_boolean(False)), tags=["baseline"])

    _register(registry, "min_max_normalize", "Min-Max 归一化", "归一化", "将强度缩放到 0-1。", preprocessing.min_max_normalize, tags=["normalize"])
    _register(registry, "z_score_normalize", "Z-score 归一化", "归一化", "按均值和标准差归一化。", preprocessing.z_score_normalize, tags=["normalize"])
    _register(registry, "vector_normalize", "向量归一化", "归一化", "按 L2 范数归一化。", preprocessing.vector_normalize, tags=["normalize"])
    _register(registry, "area_normalize", "面积归一化", "归一化", "按曲线面积归一化。", preprocessing.area_normalize, tags=["normalize"])
    _register(registry, "max_intensity_normalize", "最大强度归一化", "归一化", "按最大绝对强度归一化。", preprocessing.max_intensity_normalize, tags=["normalize"])
    _register(registry, "standard_normal_variate", "SNV 标准正态变量", "归一化", "对单条光谱执行 SNV。", preprocessing.standard_normal_variate, tags=["normalize"])
    _register(registry, "multiplicative_scatter_correction", "MSC 散射校正", "归一化", "执行乘法散射校正。", preprocessing.multiplicative_scatter_correction, default_params={}, param_schema=_schema(reference=_array("可选参考光谱")), tags=["normalize"])

    _register(registry, "find_peaks_basic", "基础峰检测", "峰检测", "使用 scipy.find_peaks 检测峰位。", feature_extraction.find_peaks_basic, output_type="peaks", default_params={"distance": 5}, param_schema=_schema(distance=_integer(5), height=_number(0)), tags=["peaks"])
    _register(registry, "find_peaks_prominence", "显著性峰检测", "峰检测", "按 prominence 检测峰位。", feature_extraction.find_peaks_prominence, output_type="peaks", default_params={"distance": 5, "prominence": 0.05}, param_schema=_schema(distance=_integer(5), prominence=_number(0.05)), tags=["peaks"])
    _register(registry, "peak_area", "峰面积", "峰检测", "估计每个峰附近窗口面积。", feature_extraction.peak_area, output_type="peaks", default_params={"half_window": 8}, param_schema=_schema(half_window=_integer(8)), tags=["peaks"])
    _register(registry, "peak_height", "峰高", "峰检测", "统计峰高。", feature_extraction.peak_height, output_type="peaks", tags=["peaks"])
    _register(registry, "peak_width", "峰宽", "峰检测", "计算半高宽。", feature_extraction.peak_width, output_type="peaks", default_params={"rel_height": 0.5}, param_schema=_schema(rel_height=_number(0.5)), tags=["peaks"])
    _register(registry, "peak_table_export", "导出峰表", "峰检测", "把峰检测结果整理为表格 artifact。", feature_extraction.peak_table_export, output_type="table", tags=["peaks"])

    _register(registry, "estimate_snr", "估计信噪比", "质量控制", "基于一阶差分估算噪声并计算 SNR。", feature_extraction.estimate_snr, output_type="metrics", tags=["qc"])
    _register(registry, "baseline_drift_score", "基线漂移评分", "质量控制", "用线性趋势估计基线漂移程度。", feature_extraction.baseline_drift_score, output_type="metrics", tags=["qc"])
    _register(registry, "saturation_check", "饱和检查", "质量控制", "统计接近最大值的饱和点比例。", feature_extraction.saturation_check, output_type="metrics", tags=["qc"])
    _register(registry, "cosmic_ray_check", "宇宙射线尖峰检查", "质量控制", "用 robust z-score 粗略检查尖峰异常。", feature_extraction.cosmic_ray_check, output_type="metrics", tags=["qc"])
    _register(registry, "fluorescence_background_score", "荧光背景评分", "质量控制", "用二次背景拟合比例评估荧光背景。", feature_extraction.fluorescence_background_score, output_type="metrics", tags=["qc"])
    _register(registry, "spectrum_quality_score", "光谱质量总分", "质量控制", "汇总 SNR、漂移、饱和和尖峰风险。", feature_extraction.spectrum_quality_score, output_type="metrics", tags=["qc"])

    _register(registry, "collect_basic_features", "基础特征提取", "特征提取", "提取均值、标准差、极值和面积等基础特征。", postprocessing.collect_basic_features, output_type="features", tags=["features"])

    ml_schema = _schema(train_features=_array("训练特征二维数组"), train_targets=_array("训练目标一维数组"))
    _register(registry, "svr_regressor", "SVR 回归", "机器学习", "使用用户提供训练数据拟合 SVR 并预测当前光谱。", classical_ml.svr_regressor, input_type="features", output_type="prediction", default_params={"C": 1.0, "epsilon": 0.1}, param_schema=ml_schema, tags=["ml", "regression"])
    _register(registry, "random_forest_regressor", "随机森林回归", "机器学习", "使用用户提供训练数据拟合随机森林并预测当前光谱。", classical_ml.random_forest_regressor, input_type="features", output_type="prediction", default_params={"n_estimators": 80, "random_state": 42}, param_schema=ml_schema, tags=["ml", "regression"])
    _register(registry, "pls_regressor", "PLS 回归", "机器学习", "使用用户提供训练数据拟合 PLS 并预测当前光谱。", classical_ml.pls_regressor, input_type="features", output_type="prediction", default_params={"n_components": 2}, param_schema=ml_schema, tags=["ml", "regression"])
    _register(registry, "linear_regressor", "线性回归", "机器学习", "使用用户提供训练数据拟合线性回归并预测当前光谱。", classical_ml.linear_regressor, input_type="features", output_type="prediction", param_schema=ml_schema, tags=["ml", "regression"])
    _register(registry, "ridge_regressor", "Ridge 回归", "机器学习", "使用用户提供训练数据拟合 Ridge 并预测当前光谱。", classical_ml.ridge_regressor, input_type="features", output_type="prediction", default_params={"alpha": 1.0}, param_schema=ml_schema, tags=["ml", "regression"])
    _register(registry, "lasso_regressor", "Lasso 回归", "机器学习", "使用用户提供训练数据拟合 Lasso 并预测当前光谱。", classical_ml.lasso_regressor, input_type="features", output_type="prediction", default_params={"alpha": 0.01}, param_schema=ml_schema, tags=["ml", "regression"])

    for algorithm_id, display_name, model_file, handler in [
        ("cnn_1d_classifier", "1D CNN 分类器", "cnn_1d_classifier.pt", deep_learning.cnn_1d_classifier),
        ("cnn_1d_regressor", "1D CNN 回归器", "cnn_1d_regressor.pt", deep_learning.cnn_1d_regressor),
        ("autoencoder_denoise", "Autoencoder 去噪", "autoencoder_denoise.pt", deep_learning.autoencoder_denoise),
        ("cdae_denoise", "CDAE 去噪", "cdae_reg_model.pt", deep_learning.cdae_denoise),
        ("cae_baseline_prediction", "CAE+ 基线预测", "caeplus_model.pt", deep_learning.cae_baseline_prediction),
    ]:
        reason = _dl_unavailable_reason(model_file)
        _register(
            registry,
            algorithm_id,
            display_name,
            "深度学习",
            "深度学习模型占位；未配置或未接入推理适配器时不可运行。",
            handler,
            requires_model_file=True,
            model_file_key=model_file,
            available=False,
            unavailable_reason=reason,
            tags=["deep_learning", "placeholder"],
        )

    return registry


_REGISTRY: AlgorithmRegistry | None = None


def get_algorithm_registry() -> AlgorithmRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = build_registry()
    return _REGISTRY

