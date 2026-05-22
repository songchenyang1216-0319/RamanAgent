# RamanAgent Skill 候选分析报告

## 1. 当前项目结构概览

本次分析重点覆盖了以下目录：

- `backend/`
- `frontend/`
- `apps/`
- `raman_core/`
- `scripts/`
- `tests/`

当前项目的核心链路已经比较清晰：

`CSV 文件 -> raman_core.methanol.* 核心算法 -> backend.services.* 服务封装 -> backend.agent.tools.* 工具层 -> FastAPI 接口 -> frontend 页面`

其中：

- `raman_core/methanol/` 是真正的算法与推理核心
- `backend/services/` 是较适合做 Skill 调用的服务层
- `backend/agent/tools/` 已经存在一批“准 Skill”雏形
- `frontend/` 当前仍是“三栏式工作台”页面，不是聊天式界面
- `apps/ui_v3.py` 是本地 PyQt 演示程序，不适合作为 Web Skill 主入口
- `scripts/train_v3.py` 是训练脚本，适合作为训练类能力来源，但不适合直接暴露给在线 Agent

## 2. 可封装 Skill 总表

| 分类 | Skill 名称 | 当前代码位置 | 封装难度 | 优先级 |
|---|---|---|---|---|
| A 光谱文件读取 | `spectrum_loader_skill` | `backend/agent/tools/spectral_tools/spectrum_loader.py::load_raman_csv`、`raman_core/methanol/spectrum_io.py::read_csv_spectrum` | 低 | P0 必须优先 |
| B 光谱预处理 | `spectrum_preprocess_skill` | `raman_core/methanol/preprocess.py` | 中 | P1 建议尽快做 |
| C 基线校正 | `baseline_correction_skill` | `raman_core/methanol/preprocess.py::baseline_als`、`correct_by_baseline` | 中 | P1 建议尽快做 |
| D 去噪/重建 | `cdae_denoise_skill` | `raman_core/methanol/predictor.py::_run_cdae_single`、`raman_core/methanol/models.py::ConvAutoEncoder` | 中 | P1 建议尽快做 |
| D 去噪/重建 | `caeplus_baseline_estimation_skill` | `raman_core/methanol/predictor.py::_run_caeplus_single`、`raman_core/methanol/models.py::CAEPlusBaseline` | 中 | P1 建议尽快做 |
| E 模型预测 | `methanol_prediction_skill` | `backend/services/methanol_service.py::predict_methanol`、`raman_core/methanol/predictor.py::MethanolPredictor.predict` | 低 | P0 必须优先 |
| F 回归/融合 | `model_fusion_regression_skill` | `backend/services/methanol_service.py::calculate_model_disagreement`、`build_public_prediction_result` | 低 | P1 建议尽快做 |
| G 可视化绘图 | `raman_plot_skill` | `raman_core/methanol/visualization.py::save_stage_figures` | 低 | P1 建议尽快做 |
| H 实验报告生成 | `experiment_report_skill` | `backend/services/report_service.py::generate_methanol_markdown_report` | 低 | P1 建议尽快做 |
| I 会话/对话辅助 | `agent_chat_helper_skill` | `backend/agent/agent_service.py`、`backend/agent/session_store.py` | 中 | P2 后续增强 |
| I 会话/对话辅助 | `history_lookup_skill` | `backend/services/history_service.py`、`backend/agent/tools/history_tool.py` | 低 | P1 建议尽快做 |
| J 模型健康检查 | `model_health_check_skill` | `backend/services/model_registry_service.py::check_model_artifacts`、`get_default_model` | 低 | P0 必须优先 |
| G/H 综合分析 | `professional_spectral_analysis_skill` | `backend/agent/tools/spectral_tools/spectral_summary_tool.py::analyze_spectrum_professionally` | 中 | P1 建议尽快做 |
| G 光谱知识解释 | `peak_annotation_skill` | `backend/agent/tools/spectral_tools/peak_detection_tool.py`、`backend/knowledge/raman_peaks.py` | 低 | P2 后续增强 |
| J/OOD 健康检查 | `ood_risk_assessment_skill` | `backend/agent/tools/spectral_tools/spectral_summary_tool.py::_analyze_ood_risk` | 中 | P2 后续增强 |

本次共识别出 **15 个候选 Skill**。

## 3. 每个 Skill 的详细说明

### 3.1 `spectrum_loader_skill`

1. 当前对应代码位置
   - `backend/agent/tools/spectral_tools/spectrum_loader.py::load_raman_csv`
   - `raman_core/methanol/spectrum_io.py::read_csv_spectrum`
2. 当前功能描述
   - 读取 Raman CSV 文件，尝试多种编码，过滤非数值行，返回排序后的波数和强度数组，以及基础统计信息。
3. 为什么适合封装成 Skill
   - 输入是明确的 `csv_path`
   - 输出是明确的结构化光谱数据和统计结果
   - 可以在“上传后预检查”“只看文件质量”“后续算法前置校验”中独立复用
4. 建议输入参数 schema
   ```json
   {
     "file_path": "str",
     "allow_encodings": "list[str] | None",
     "min_points": "int | None"
   }
   ```
5. 建议输出结果 schema
   ```json
   {
     "success": "bool",
     "skill_name": "str",
     "summary": "str",
     "data": {
       "points": "int",
       "x_min": "float",
       "x_max": "float",
       "y_min": "float",
       "y_max": "float",
       "x": "list[float]",
       "y": "list[float]"
     },
     "plots": [],
     "errors": "list[str]"
   }
   ```
6. 当前代码存在的问题
   - 现在存在两套相近读取实现，逻辑重复
   - 一个偏算法核心，一个偏 Agent 工具，尚未统一
   - 目前没有统一 `SkillResult`
7. 封装难度
   - 低
8. 推荐优先级
   - P0 必须优先
9. 推荐改造方式
   - 优先包装现有函数
   - 对外统一输入输出结构
   - 后续再考虑去重

### 3.2 `spectrum_preprocess_skill`

1. 当前对应代码位置
   - `raman_core/methanol/preprocess.py::interpolate_to_axis`
   - `raman_core/methanol/preprocess.py::apply_sg_smoothing`
   - `raman_core/methanol/preprocess.py::preprocess_for_regression_branch`
   - `raman_core/methanol/preprocess.py::preprocess_for_als_branch`
2. 当前功能描述
   - 完成统一波数轴插值、SG 平滑、归一化、ALS 分支预处理。
3. 为什么适合封装成 Skill
   - 输入可以是数组或文件读取结果
   - 输出是可复用的中间光谱
   - 适合支持“只做预处理”“只看预处理图”的 Agent 调用
4. 建议输入参数 schema
   ```json
   {
     "x": "list[float] | None",
     "y": "list[float] | None",
     "file_path": "str | None",
     "target_axis": "list[float] | None",
     "sg_window": "int | None",
     "sg_order": "int | None",
     "mode": "str"
   }
   ```
5. 建议输出结果 schema
   ```json
   {
     "success": "bool",
     "skill_name": "str",
     "summary": "str",
     "data": {
       "aligned_y": "list[float]",
       "smoothed_y": "list[float]",
       "normalized_y": "list[float]",
       "baseline_y": "list[float] | None"
     },
     "plots": [],
     "errors": "list[str]"
   }
   ```
6. 当前代码存在的问题
   - 目前主要在算法内部被调用，不适合直接被外部 Skill 层消费
   - 没有统一的结构化摘要
7. 封装难度
   - 中
8. 推荐优先级
   - P1 建议尽快做
9. 推荐改造方式
   - 只需要包装现有函数
   - 补一层统一参数解析和异常处理

### 3.3 `baseline_correction_skill`

1. 当前对应代码位置
   - `raman_core/methanol/preprocess.py::baseline_als`
   - `raman_core/methanol/preprocess.py::correct_by_baseline`
   - `backend/agent/tools/spectral_tools/baseline_quality_tool.py::analyze_baseline_quality`
2. 当前功能描述
   - 做 ALS 基线估计、基线扣除，以及基线风险质量分析。
3. 为什么适合封装成 Skill
   - 输入明确：光谱数组和参数
   - 输出明确：基线、校正后光谱、风险评估
   - 适合用户说“帮我做基线校正”“看看基线漂移是否严重”
4. 建议输入参数 schema
   ```json
   {
     "y": "list[float] | None",
     "file_path": "str | None",
     "lam": "float | None",
     "p": "float | None",
     "niter": "int | None"
   }
   ```
5. 建议输出结果 schema
   ```json
   {
     "success": "bool",
     "skill_name": "str",
     "summary": "str",
     "data": {
       "baseline": "list[float]",
       "corrected": "list[float]",
       "baseline_level": "str",
       "metrics": "dict"
     },
     "plots": [],
     "errors": "list[str]"
   }
   ```
6. 当前代码存在的问题
   - 现在“校正”和“质量判断”分散在不同模块
   - 没有一个统一的可直接调用入口
7. 封装难度
   - 中
8. 推荐优先级
   - P1 建议尽快做
9. 推荐改造方式
   - 拆分“计算基线”和“评价基线”两个步骤
   - 统一输出结构

### 3.4 `cdae_denoise_skill`

1. 当前对应代码位置
   - `raman_core/methanol/predictor.py::_run_cdae_single`
   - `raman_core/methanol/models.py::ConvAutoEncoder`
2. 当前功能描述
   - 对预处理后的光谱执行 CDAE 去噪。
3. 为什么适合封装成 Skill
   - 输入输出边界明确
   - 很适合未来支持“只做去噪/重建”的聊天指令
4. 建议输入参数 schema
   ```json
   {
     "spectrum": "list[float]",
     "model_type": "str | None"
   }
   ```
5. 建议输出结果 schema
   ```json
   {
     "success": "bool",
     "skill_name": "str",
     "summary": "str",
     "data": {
       "denoised_spectrum": "list[float]"
     },
     "plots": [],
     "errors": "list[str]"
   }
   ```
6. 当前代码存在的问题
   - 当前方法是 `MethanolPredictor` 私有方法，不利于外部复用
   - 强依赖 predictor 已成功初始化
7. 封装难度
   - 中
8. 推荐优先级
   - P1 建议尽快做
9. 推荐改造方式
   - 需要把私有运行逻辑包装到 Skill 内
   - 不要重写模型逻辑

### 3.5 `caeplus_baseline_estimation_skill`

1. 当前对应代码位置
   - `raman_core/methanol/predictor.py::_run_caeplus_single`
   - `raman_core/methanol/models.py::CAEPlusBaseline`
2. 当前功能描述
   - 用 CAE+ 预测光谱基线背景。
3. 为什么适合封装成 Skill
   - 输入是光谱数组
   - 输出是估计基线
   - 能支持独立的基线重建/解释能力
4. 建议输入参数 schema
   ```json
   {
     "spectrum": "list[float]"
   }
   ```
5. 建议输出结果 schema
   ```json
   {
     "success": "bool",
     "skill_name": "str",
     "summary": "str",
     "data": {
       "estimated_baseline": "list[float]"
     },
     "plots": [],
     "errors": "list[str]"
   }
   ```
6. 当前代码存在的问题
   - 也是私有方法
   - 只能嵌在完整预测链路里用
7. 封装难度
   - 中
8. 推荐优先级
   - P1 建议尽快做
9. 推荐改造方式
   - 与 `cdae_denoise_skill` 类似，先包装调用，不改模型

### 3.6 `methanol_prediction_skill`

1. 当前对应代码位置
   - `backend/services/methanol_service.py::predict_methanol`
   - `raman_core/methanol/predictor.py::MethanolPredictor.predict`
2. 当前功能描述
   - 读取 CSV、插值、SG 平滑、ALS 去基线、CDAE 去噪、CAE+ 基线估计、SVR/RF 融合预测，并返回结构化结果。
3. 为什么适合封装成 Skill
   - 输入明确：`file_path` 和可选 `metadata`
   - 输出明确：预测值、单位、图谱、中间结果、pipeline、confidence
   - 本身就是最核心的 Agent 能力
4. 建议输入参数 schema
   ```json
   {
     "file_path": "str",
     "metadata": "dict | None",
     "include_intermediate": "bool | None"
   }
   ```
5. 建议输出结果 schema
   ```json
   {
     "success": "bool",
     "skill_name": "str",
     "summary": "str",
     "data": {
       "predicted_value": "float",
       "unit": "str",
       "model_version": "str | None",
       "svr_prediction": "float",
       "rf_prediction": "float",
       "confidence": "dict",
       "model_disagreement": "dict",
       "pipeline": "list[str]"
     },
     "plots": "list[str]",
     "errors": "list[str]"
   }
   ```
6. 当前代码存在的问题
   - 结果结构在 `service`、`tool`、`api` 三层有不同命名
   - `fusion_prediction` / `final_prediction` 等字段风格不完全统一
   - 还没有独立的 Skill 层
7. 封装难度
   - 低
8. 推荐优先级
   - P0 必须优先
9. 推荐改造方式
   - 只需要包装现有服务层
   - 统一输入输出字段

### 3.7 `model_fusion_regression_skill`

1. 当前对应代码位置
   - `backend/services/methanol_service.py::calculate_model_disagreement`
   - `backend/services/methanol_service.py::build_public_prediction_result`
2. 当前功能描述
   - 计算 SVR/RF 差异，给出一致性提醒，组织最终对外预测结构。
3. 为什么适合封装成 Skill
   - 可以作为预测后的独立解释模块
   - 输入是模型结果，输出是融合后的风险摘要
4. 建议输入参数 schema
   ```json
   {
     "svr_prediction": "float",
     "rf_prediction": "float",
     "fusion_prediction": "float"
   }
   ```
5. 建议输出结果 schema
   ```json
   {
     "success": "bool",
     "skill_name": "str",
     "summary": "str",
     "data": {
       "absolute_difference": "float",
       "relative_difference": "float",
       "warning": "bool",
       "message": "str"
     },
     "plots": [],
     "errors": []
   }
   ```
6. 当前代码存在的问题
   - 当前埋在服务层内部
   - 不能被单独调用
7. 封装难度
   - 低
8. 推荐优先级
   - P1 建议尽快做
9. 推荐改造方式
   - 只需包装现有函数

### 3.8 `raman_plot_skill`

1. 当前对应代码位置
   - `raman_core/methanol/visualization.py::save_stage_figures`
2. 当前功能描述
   - 保存四阶段图谱并返回文件路径。
3. 为什么适合封装成 Skill
   - 输入输出明确，天然适合供对话界面调用
   - 可支撑“只重新出图”“解释四张图”
4. 建议输入参数 schema
   ```json
   {
     "sample_name": "str",
     "common_axis": "list[float]",
     "raw": "list[float]",
     "preprocessed": "list[float]",
     "cdae": "list[float]",
     "final": "list[float]"
   }
   ```
5. 建议输出结果 schema
   ```json
   {
     "success": "bool",
     "skill_name": "str",
     "summary": "str",
     "data": {
       "figure_map": "dict"
     },
     "plots": "list[str]",
     "errors": []
   }
   ```
6. 当前代码存在的问题
   - 只返回本地路径，没有统一转成可访问 URL
7. 封装难度
   - 低
8. 推荐优先级
   - P1 建议尽快做
9. 推荐改造方式
   - 包装现有函数
   - 补充 URL 映射

### 3.9 `experiment_report_skill`

1. 当前对应代码位置
   - `backend/services/report_service.py::generate_methanol_markdown_report`
   - `backend/agent/tools/report_tool.py::generate_report_tool`
2. 当前功能描述
   - 根据预测结果、专业分析和解释文本生成 Markdown/HTML 报告。
3. 为什么适合封装成 Skill
   - 输入清晰、输出明确
   - 可独立服务于“生成报告”“重新导出报告”
4. 建议输入参数 schema
   ```json
   {
     "result": "dict",
     "llm_explanation": "str | None",
     "professional_analysis": "dict | None",
     "model_info": "dict | None",
     "experiment_metadata": "dict | None"
   }
   ```
5. 建议输出结果 schema
   ```json
   {
     "success": "bool",
     "skill_name": "str",
     "summary": "str",
     "data": {
       "report_id": "str",
       "report_markdown_path": "str",
       "report_html_path": "str"
     },
     "plots": [],
     "errors": []
   }
   ```
6. 当前代码存在的问题
   - 目前仍然是工具层风格，不是统一 Skill 风格
   - 强耦合现有结果字段
7. 封装难度
   - 低
8. 推荐优先级
   - P1 建议尽快做
9. 推荐改造方式
   - 只需包装现有工具/服务

### 3.10 `agent_chat_helper_skill`

1. 当前对应代码位置
   - `backend/agent/agent_service.py`
   - `backend/agent/session_store.py`
2. 当前功能描述
   - 负责意图识别、会话记忆、历史分析上下文追问等。
3. 为什么适合封装成 Skill
   - 从功能上可独立为“会话辅助能力”
   - 适合未来做多 Skill 编排
4. 建议输入参数 schema
   ```json
   {
     "message": "str",
     "session_id": "str | None"
   }
   ```
5. 建议输出结果 schema
   ```json
   {
     "success": "bool",
     "skill_name": "str",
     "summary": "str",
     "data": {
       "intent": "str",
       "reply": "str",
       "session_id": "str"
     },
     "plots": [],
     "errors": []
   }
   ```
6. 当前代码存在的问题
   - 逻辑很大、职责偏多
   - 混合了路由、工具选择、自然语言回复
7. 封装难度
   - 中
8. 推荐优先级
   - P2 后续增强
9. 推荐改造方式
   - 暂不重构大块逻辑
   - 先保留现有 AgentService，后续再拆

### 3.11 `history_lookup_skill`

1. 当前对应代码位置
   - `backend/services/history_service.py`
   - `backend/agent/tools/history_tool.py`
   - `backend/agent/tools/spectral_tools/similarity_tool.py`
2. 当前功能描述
   - 列出历史记录、获取详情、寻找相似历史样品。
3. 为什么适合封装成 Skill
   - 输入输出清晰
   - 很适合聊天式工作流里的“最近实验”“查看历史详情”
4. 建议输入参数 schema
   ```json
   {
     "mode": "str",
     "task_id": "str | None",
     "limit": "int | None",
     "current_prediction_result": "dict | None"
   }
   ```
5. 建议输出结果 schema
   ```json
   {
     "success": "bool",
     "skill_name": "str",
     "summary": "str",
     "data": {
       "items": "list",
       "item": "dict | None",
       "similar_records": "list"
     },
     "plots": [],
     "errors": []
   }
   ```
6. 当前代码存在的问题
   - 历史检索和相似度对比分散
7. 封装难度
   - 低
8. 推荐优先级
   - P1 建议尽快做
9. 推荐改造方式
   - 统一历史查询入口

### 3.12 `model_health_check_skill`

1. 当前对应代码位置
   - `backend/services/model_registry_service.py::check_model_artifacts`
   - `backend/services/model_registry_service.py::get_default_model`
   - `backend/agent/tools/artifact_tool.py::check_artifacts_tool`
2. 当前功能描述
   - 检查模型版本、模型文件、缺失工件、回退加载情况。
3. 为什么适合封装成 Skill
   - 非常符合 Agent “检查模型”“当前模型是什么”的调用场景
   - 输入简单，输出结构化，复用价值高
4. 建议输入参数 schema
   ```json
   {
     "model_version": "str | None",
     "check_loadable": "bool | None"
   }
   ```
5. 建议输出结果 schema
   ```json
   {
     "success": "bool",
     "skill_name": "str",
     "summary": "str",
     "data": {
       "model_version": "str | None",
       "model_name": "str | None",
       "artifact_dir": "str | None",
       "missing_files": "list",
       "existing_files": "list",
       "loadable": "bool | None"
     },
     "plots": [],
     "errors": "list[str]"
   }
   ```
6. 当前代码存在的问题
   - 目前只有“文件是否存在”的检查
   - 没有统一做一次“是否可实际加载”的 Skill 封装
7. 封装难度
   - 低
8. 推荐优先级
   - P0 必须优先
9. 推荐改造方式
   - 包装现有 registry/service
   - 额外增加 predictor 可加载校验

### 3.13 `professional_spectral_analysis_skill`

1. 当前对应代码位置
   - `backend/agent/tools/spectral_tools/spectral_summary_tool.py::analyze_spectrum_professionally`
2. 当前功能描述
   - 综合峰识别、质量评分、基线分析、历史相似样品、OOD 风险并生成专业总结。
3. 为什么适合封装成 Skill
   - 输入输出都清晰
   - 很适合作为上传 CSV 后的二级分析能力
4. 建议输入参数 schema
   ```json
   {
     "csv_path": "str",
     "prediction_result": "dict | None"
   }
   ```
5. 建议输出结果 schema
   ```json
   {
     "success": "bool",
     "skill_name": "str",
     "summary": "str",
     "data": {
       "professional_summary": "dict",
       "quality_analysis": "dict",
       "baseline_analysis": "dict",
       "peak_analysis": "dict",
       "similarity_analysis": "dict",
       "ood_risk": "dict"
     },
     "plots": [],
     "errors": "list[str]"
   }
   ```
6. 当前代码存在的问题
   - 聚合逻辑很强，但不是统一 Skill 框架
   - 内部依赖若干工具函数，结构较松散
7. 封装难度
   - 中
8. 推荐优先级
   - P1 建议尽快做
9. 推荐改造方式
   - 直接包装现有聚合函数

### 3.14 `peak_annotation_skill`

1. 当前对应代码位置
   - `backend/agent/tools/spectral_tools/peak_detection_tool.py::detect_peaks`
   - `backend/knowledge/raman_peaks.py::annotate_peaks`
2. 当前功能描述
   - 识别主要峰位并附加谨慎的甲醇相关知识注释。
3. 为什么适合封装成 Skill
   - 非常适合支持“帮我看看这个峰是什么”的自然语言请求
4. 建议输入参数 schema
   ```json
   {
     "csv_path": "str",
     "top_n": "int | None"
   }
   ```
5. 建议输出结果 schema
   ```json
   {
     "success": "bool",
     "skill_name": "str",
     "summary": "str",
     "data": {
       "peaks": "list",
       "peak_count": "int"
     },
     "plots": [],
     "errors": []
   }
   ```
6. 当前代码存在的问题
   - 目前结果可用，但没有统一 Skill 层
7. 封装难度
   - 低
8. 推荐优先级
   - P2 后续增强
9. 推荐改造方式
   - 包装现有工具即可

### 3.15 `ood_risk_assessment_skill`

1. 当前对应代码位置
   - `backend/agent/tools/spectral_tools/spectral_summary_tool.py::_analyze_ood_risk`
2. 当前功能描述
   - 基于训练范围、潜在特征距离、光谱质量和基线质量给出分布外风险评估。
3. 为什么适合封装成 Skill
   - 适合做“结果可靠性”解释
   - 与普通预测分离后，能独立复用
4. 建议输入参数 schema
   ```json
   {
     "prediction_result": "dict",
     "quality_analysis": "dict | None",
     "baseline_analysis": "dict | None"
   }
   ```
5. 建议输出结果 schema
   ```json
   {
     "success": "bool",
     "skill_name": "str",
     "summary": "str",
     "data": {
       "level": "str",
       "score": "float",
       "warnings": "list[str]",
       "factors": "dict"
     },
     "plots": [],
     "errors": []
   }
   ```
6. 当前代码存在的问题
   - 目前是私有聚合函数
   - 不能被接口单独调用
7. 封装难度
   - 中
8. 推荐优先级
   - P2 后续增强
9. 推荐改造方式
   - 从聚合分析中抽出统一入口

## 4. 不适合封装成 Skill 的代码

以下内容不建议封装成 Agent Skill：

1. `frontend/style.css`
   - 原因：纯样式文件，没有业务输入输出。
2. `frontend/index.html`
   - 原因：主要是布局结构，不是独立业务能力。
3. `frontend/app.js` 中纯渲染函数
   - 例如 `appendChatMessage`、`renderPrediction` 这一类 UI 渲染逻辑。
   - 原因：只服务前端页面展示，不适合作为 Agent Skill。
4. `backend/main.py` 中静态文件挂载与 FastAPI 启动代码
   - 原因：是应用装配层，不是可复用业务能力。
5. `apps/ui_v3.py`
   - 原因：PyQt 本地演示程序，强依赖桌面界面交互。
   - 但其中对 `MethanolPredictor.predict` 的使用方式可作为参考。
6. `scripts/train_v3.py`
   - 原因：属于离线训练脚本，不适合直接作为在线分析 Skill。
   - 后续可抽“训练任务 Skill”，但不是本轮重点。
7. `tests/`
   - 原因：测试代码不应该直接作为 Skill 封装对象。
8. `backend/db/database.py`
   - 原因：底层连接工具，不是对话级业务能力。
9. 纯静态知识常量
   - 例如 `backend/knowledge/raman_peaks.py` 中静态表本身不是 Skill。
   - 它更适合作为 `peak_annotation_skill` 的依赖资源。

## 5. 推荐优先级

### P0 必须优先

1. `methanol_prediction_skill`
2. `spectrum_loader_skill`
3. `model_health_check_skill`

### P1 建议尽快做

1. `spectrum_preprocess_skill`
2. `baseline_correction_skill`
3. `cdae_denoise_skill`
4. `caeplus_baseline_estimation_skill`
5. `model_fusion_regression_skill`
6. `raman_plot_skill`
7. `experiment_report_skill`
8. `history_lookup_skill`
9. `professional_spectral_analysis_skill`

### P2 后续增强

1. `agent_chat_helper_skill`
2. `peak_annotation_skill`
3. `ood_risk_assessment_skill`

### P3 暂时不用

1. 训练类脚本 Skill
2. PyQt 演示程序封装
3. 纯 UI 样式相关逻辑

## 6. 推荐目录结构

建议在 `backend/` 下新增 Skill 封装层：

```text
backend/
  skills/
    __init__.py
    base.py
    registry.py
    raman_methanol_skill.py
    spectrum_loader_skill.py
    model_health_check_skill.py
```

后续再逐步扩展：

```text
backend/
  skills/
    spectrum_preprocess_skill.py
    baseline_correction_skill.py
    report_generation_skill.py
    professional_spectral_analysis_skill.py
    history_lookup_skill.py
```

## 7. 推荐改造步骤

### 阶段一

1. 固化本报告
2. 选定 P0 Skill
3. 明确哪些能力直接包装、哪些能力只做最小抽取

### 阶段二第一步

1. 新增 `backend/skills/base.py`
2. 定义 `SkillResult` 和 `BaseSkill`
3. 新增 `backend/skills/registry.py`
4. 先注册 3 个 P0 Skill

### 阶段二第二步

1. 用 `spectrum_loader_skill` 做上传文件前置校验
2. 用 `methanol_prediction_skill` 调用现有预测链路
3. 用 `model_health_check_skill` 给聊天接口和顶部状态栏提供数据

### 阶段二第三步

1. 改造 `/api/agent/chat`
2. 让它同时支持纯文本聊天和带文件聊天
3. 统一返回 `messages` 数组

### 阶段二第四步

1. 把前端改成聊天式主界面
2. 保留顶部状态栏
3. 去掉中间上传面板和右侧结果面板的主流程地位
4. 结果统一进入聊天流

## 8. 风险点

1. 现有 Agent 接口 `/api/agent/chat` 已存在 JSON 聊天协议，改造成同时支持 `FormData` 时要兼容旧调用。
2. 现有前端依赖 `/api/agent/analyze-file`，如果完全替换，容易影响旧功能。
3. `MethanolPredictor` 依赖 `torch` 和模型文件，若模型损坏或缺失，必须在 Skill 和接口层清晰报错。
4. `frontend/app.js` 当前体量较大，直接重写风险高，建议以“保留状态获取/历史查询逻辑，重做聊天渲染主流程”的方式渐进改造。
5. `backend/agent/agent_service.py` 逻辑较重，本轮不宜大拆，只做接口适配和最小接入。
6. 当前项目里同一能力有多层包装，字段命名不统一，改造时要优先保证对外 JSON 统一，而不是内部一次性彻底重构。

## 9. 下一步 Codex 改造建议

下一步建议按以下顺序继续：

1. 新建 `backend/skills/`，落地 P0 Skill 架构。
2. 在不删除旧接口的前提下，把 `/api/agent/chat` 改成统一聊天入口，支持文本和 CSV 上传。
3. 新增一个最小公共分析函数，例如：
   `analyze_spectrum_file(file_path: str, metadata: dict | None = None) -> dict`
4. 前端改成 ChatGPT 风格：顶部状态栏 + 中间聊天区 + 底部输入栏 + 左侧上传按钮。
5. 保留旧的 `/api/agent/analyze-file` 与模型/历史接口，作为兼容层。

## 10. 本轮建议优先封装的 3 个 Skill

1. `methanol_prediction_skill`
2. `spectrum_loader_skill`
3. `model_health_check_skill`

原因：

- 三者正好覆盖“上传文件 -> 基本校验 -> 核心预测 -> 模型状态反馈”的最短闭环
- 这三项是聊天式 CSV 分析界面最基础、最必要的后端能力
- 都能直接复用现有代码，改造成本最低，风险最小
