# FastAPI 后端函数说明

本文档说明 RamanAgent 后端中的关键函数，以及它们在预测、解释、报告和 Web 展示链路中的作用。

## 1. backend/main.py

### `root()`

- 路径：`GET /`
- 作用：快速确认服务已启动。

### `health()`

- 路径：`GET /health`
- 作用：健康检查。

### 静态资源挂载

- `/static/figures`
  - 对应 `outputs/figures`
- `/static/reports`
  - 对应 `outputs/reports`
- `/app`
  - 对应 `frontend`

## 2. backend/api/methanol_api.py

### `sanitize_csv_filename(file_name: str) -> str`

- 作用：清理上传文件名，避免路径穿越与危险字符。

### `build_unique_raw_path(file_name: str) -> Path`

- 作用：在 `data/raw/` 中生成不覆盖旧文件的唯一保存路径。

### `save_uploaded_csv(file: UploadFile) -> Path`

- 作用：复用上传保存逻辑。

### `build_figure_web_urls(figures: dict) -> dict`

- 作用：将本地图像路径转换为浏览器可访问的相对 URL。

### `build_report_web_urls(report: dict) -> dict`

- 作用：生成报告查看 URL 与下载 URL。

### `predict(...) -> dict`

- 路径：`POST /api/methanol/predict`
- 作用：上传 CSV 并执行预测。

### `predict_demo(...) -> dict`

- 路径：`POST /api/methanol/predict-demo`
- 作用：对 `data/demo/` 中的样例文件执行预测。

### `explain_result(request: ExplainResultRequest) -> ExplainResultResponse`

- 路径：`POST /api/methanol/explain-result`
- 作用：基于公开预测结果生成中文解释。

### `predict_report(...) -> dict`

- 路径：`POST /api/methanol/predict-report`
- 作用：上传 CSV 后完成预测、可选解释和 Markdown 报告生成。
- 新增返回字段：
  - `web_urls.figures.raw`
  - `web_urls.figures.preprocessed`
  - `web_urls.figures.cdae`
  - `web_urls.figures.final`
  - `web_urls.report_view`
  - `web_urls.report_download`

## 3. backend/api/file_api.py

### `validate_report_file_name(report_file: str) -> str`

- 作用：校验报告文件名是否合法。
- 防护内容：
  - 禁止 `../`
  - 禁止 `/`
  - 禁止 `\`

### `download_report(report_file: str)`

- 路径：`GET /api/files/reports/{report_file}/download`
- 作用：下载 Markdown 报告文件。

## 4. backend/services/methanol_service.py

### `_to_builtin(value: Any) -> Any`

- 作用：将 `numpy`、`Path` 等对象递归转换为 JSON 可序列化类型。

### `get_predictor()`

- 作用：延迟初始化并缓存 `MethanolPredictor`。

### `calculate_model_disagreement(...) -> dict`

- 作用：计算 SVR 与 RF 的预测差异，并生成风险提醒。

### `build_public_prediction_result(...) -> dict`

- 作用：将 `MethanolPredictor.predict` 的原始结果整理为接口公开返回结构。

### `predict_methanol(...) -> dict`

- 作用：服务层统一预测入口。

## 5. backend/services/llm_service.py

### `LLMService`

- 作用：封装 SiliconFlow 的 OpenAI-compatible 调用。

### `explain_methanol_result(result: dict) -> str`

- 作用：根据公开预测结果生成中文解释。

## 6. backend/services/report_service.py

### `generate_methanol_markdown_report(result: dict, llm_explanation: str | None = None) -> dict`

- 作用：根据预测结果和大模型解释生成 Markdown 报告。

## 7. 前端页面

- 路径：`/app/index.html`
- 功能：
  - 上传 CSV
  - 调用 `/api/methanol/predict-report`
  - 展示预测结果
  - 展示大模型解释
  - 展示四阶段图
  - 查看与下载报告

## 8. 历史记录服务

### `init_history_db()`

- 作用：初始化 SQLite 数据库和 `analysis_history` 表。

### `save_analysis_history(payload: dict) -> dict`

- 作用：保存一次 `predict-report` 的结果摘要。
- 不保存：
  - `intermediate`

### `list_analysis_history(limit: int = 20, offset: int = 0) -> dict`

- 作用：按时间倒序返回历史记录摘要列表。

### `get_analysis_history(task_id: str) -> dict | None`

- 作用：返回某条历史记录的详情。

### `delete_analysis_history(task_id: str) -> bool`

- 作用：删除数据库记录，不删除原始文件、图谱和报告。

## 9. 历史记录接口

### `GET /api/history`

- 作用：获取历史记录列表。

### `GET /api/history/{task_id}`

- 作用：获取单条历史记录详情。

### `DELETE /api/history/{task_id}`

- 作用：删除单条历史记录，仅删除数据库记录。
