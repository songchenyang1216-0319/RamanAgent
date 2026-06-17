# RamanAgent Demo Data

本目录放可公开演示的合成 Raman CSV，不包含真实样品或敏感实验数据。

## 文件

- `demo_raman_methanol.csv`：合成 Raman 光谱，包含 `wavenumber` 和 `intensity` 两列，用于演示上传、基础预处理、峰识别、质量评估和报告生成流程。

## 最简 Raman CSV Demo

1. 启动后端并打开前端。
2. 上传 `data/demo/demo_raman_methanol.csv`。
3. 输入：`先对这个 Raman CSV 做 basic_preprocessing，不要预测`。
4. 查看 SG 平滑、ALS 去基线、归一化后的步骤图和 Pipeline history。

## 完整 Raman Pipeline Demo

1. 上传 `demo_raman_methanol.csv`。
2. 在 Pipeline 面板选择 `basic_preprocessing`。
3. 查看每一步的 `algorithm_id`、`display_name`、`input_shape`、`output_shape`、`metrics` 和图像产物。
4. 运行 `peak_analysis`，查看峰位、峰高、峰宽、峰面积和峰表。
5. 运行 `quality_check`，查看 SNR、基线漂移、饱和风险、尖峰风险和质量总分。
6. 使用报告入口生成 Markdown/HTML 报告，最终回答下方应展示 artifacts 和图像结果。

