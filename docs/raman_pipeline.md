# Raman Pipeline 第一阶段

Raman Pipeline 第一阶段提供可组合的 Raman 光谱算法链。它不做 LLM Planner，不改变旧甲醇预测入口；旧预测仍以 `MethanolPredictor.predict` 为核心。

## 目标

- 通过 `AlgorithmSpec` 统一描述算法能力、参数、输入输出和可用性。
- 通过 `PipelineStep`、`PipelineRequest`、`PipelineResult` 表达用户自定义处理链。
- 支持前端 Pipeline Builder 选择模板、添加算法、编辑参数、运行 CSV、查看步骤状态和中间图。
- 对文件格式错误、参数错误、模型文件缺失和深度学习占位未配置返回中文错误。

## API

- `GET /api/raman/algorithms`
- `GET /api/raman/algorithms/{algorithm_id}`
- `GET /api/raman/pipeline/templates`
- `POST /api/raman/pipeline/validate`
- `POST /api/raman/pipeline/run`
- `GET /api/raman/pipeline/history`

`/api/raman/pipeline/run` 支持两种输入：

- JSON：提供 `file_path`、`steps` 或 `template_id`
- multipart：上传 `file`，同时用 `payload` 字段传 JSON

## 内置模板

- `basic_preprocessing`：读取、校验、清理、排序、去重、SG 平滑、ALS 基线、基线扣除、Min-Max 归一化。
- `quality_check`：读取清理后输出 SNR、漂移、饱和、尖峰、荧光背景和总质量分。
- `methanol_prediction`：旧甲醇预测前处理模板，不替代 `MethanolPredictor.predict`。
- `peak_analysis`：平滑、显著峰检测、峰高、峰宽、峰面积和峰表。
- `deep_learning_placeholder`：展示深度学习占位不可用原因。
- `ml_compare`：预处理和基础特征后运行经典 ML 回归器；需要用户提供训练数据参数。

## Pipeline Step 结果

每一步都会记录：

- `step_id`
- `algorithm_id`
- `display_name`
- `status`
- `params`
- `input_shape`
- `output_shape`
- `metrics`
- `artifacts`
- `warning`
- `error_message`
- `elapsed_ms`

运行器会为有光谱输出的步骤生成 PNG 图谱，保存到 `outputs/raman_pipeline/{run_id}/`。

## Skill 兼容

`RamanSpectroscopySkill` 保留旧 action，并新增：

- `list_algorithms`
- `validate_pipeline`
- `run_custom_pipeline`
- `run_template_pipeline`
- `list_pipeline_templates`
- `get_pipeline_history`
- `compare_pipelines`

