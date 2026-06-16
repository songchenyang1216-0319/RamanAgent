# Raman Pipeline 算法目录

当前注册表共 51 个算法，其中 46 个 ready，5 个深度学习占位 unavailable。

## Ready 算法

读取校验：

- `load_csv_spectrum`
- `validate_spectrum_csv`
- `infer_wavenumber_intensity_columns`
- `remove_nan_inf`
- `sort_by_wavenumber`
- `remove_duplicate_wavenumber`
- `crop_wavenumber_range`

波数轴：

- `resample_linear`
- `resample_cubic`
- `align_to_reference_axis`

平滑：

- `savitzky_golay`
- `moving_average`
- `gaussian_filter`
- `median_filter`
- `butterworth_lowpass`

基线：

- `polynomial_baseline`
- `rubberband_baseline`
- `als_baseline`
- `airpls_baseline`
- `baseline_subtraction`

归一化：

- `min_max_normalize`
- `z_score_normalize`
- `vector_normalize`
- `area_normalize`
- `max_intensity_normalize`
- `standard_normal_variate`
- `multiplicative_scatter_correction`

峰检测：

- `find_peaks_basic`
- `find_peaks_prominence`
- `peak_area`
- `peak_height`
- `peak_width`
- `peak_table_export`

质量控制：

- `estimate_snr`
- `baseline_drift_score`
- `saturation_check`
- `cosmic_ray_check`
- `fluorescence_background_score`
- `spectrum_quality_score`

特征提取：

- `collect_basic_features`

机器学习：

- `svr_regressor`
- `random_forest_regressor`
- `pls_regressor`
- `linear_regressor`
- `ridge_regressor`
- `lasso_regressor`

说明：经典机器学习算法是本地可运行的训练/预测步骤，但需要在参数中提供 `train_features` 和 `train_targets`。如果只上传单条未知光谱而没有训练数据，会返回中文参数错误。

## Unavailable 算法

深度学习占位：

- `cnn_1d_classifier`：缺少 `artifacts/cnn_1d_classifier.pt`
- `cnn_1d_regressor`：缺少 `artifacts/cnn_1d_regressor.pt`
- `autoencoder_denoise`：缺少 `artifacts/autoencoder_denoise.pt`
- `cdae_denoise`：模型文件存在，但新 Pipeline 尚未接入推理适配器
- `cae_baseline_prediction`：模型文件存在，但新 Pipeline 尚未接入推理适配器

这些算法会在注册表中返回 `available=false` 和明确 `unavailable_reason`，运行时不会假装成功。

