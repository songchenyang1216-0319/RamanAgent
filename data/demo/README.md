# Raman Demo Data

本目录保存 RamanAgent 现场演示使用的合成 Raman 光谱数据。数据由确定性函数生成，只用于功能演示、测试和文档截图，不包含真实实验样本或敏感数据。

## 文件说明

- `raman_demo_valid.csv`：格式正确、峰形清晰的合成 Raman 光谱，可用于 basic_preprocessing、peak_analysis 和 quality_check。
- `raman_demo_with_noise.csv`：在 valid 光谱基础上加入周期噪声和尖峰，用于展示 SG 平滑、ALS 去基线和质量评估。
- `raman_demo_invalid.csv`：故意构造的无效光谱，有效点不足，用于验证错误提示和失败中止。
- `demo_raman_methanol.csv`：历史演示文件，保留用于向后兼容。

## 推荐演示流程

1. 上传 `raman_demo_valid.csv`。
2. 选择 `basic_preprocessing` 模板，执行 SG 平滑、ALS 去基线和 Min-Max 归一化。
3. 运行 `peak_analysis`，查看峰识别图和峰表 artifact。
4. 运行 `quality_check`，查看 SNR、背景漂移、尖峰等质量指标。
5. 上传 `raman_demo_invalid.csv`，验证 Pipeline 会返回明确错误且不会继续执行依赖步骤。
