# LLM Planner + Tool Schema

第二阶段在旧 `IntentRouter` / `Planner` 之外新增增强规划层。旧路由不删除，增强层失败时回退旧流程。

## 流程

```text
MessageNormalizer
  -> 高置信规则判断
  -> 命中高确定性旧规则：旧 Planner
  -> 未命中：LLMPlanner
  -> JSON plan
  -> PlanValidator
  -> PlanExecutor
  -> ResponseBuilder
  -> 失败时回退旧 IntentRouter + Planner
```

接入位置：

- `backend/agent/orchestrator.py`
- `AgentOrchestrator.handle_chat()`
- 新增 `_try_enhanced_planning()`、`_should_use_legacy_rule()`、`_attach_debug_payload()`

## JSON Plan 格式

LLM Planner 必须输出 JSON：

```json
{
  "plan_type": "model | tool | skill | rag | raman_pipeline | hybrid | fallback",
  "intent": "...",
  "confidence": 0.0,
  "requires_file": true,
  "requires_confirmation": false,
  "reason": "...",
  "steps": [
    {
      "step_id": "step_001",
      "tool_name": "raman_pipeline",
      "action_name": "run_custom_pipeline",
      "args": {}
    }
  ]
}
```

LLM 输出不能直接执行，必须经过 `PlanValidator`。

## Tool Schema

当前工具目录包含：

- `raman_pipeline`
- `raman_model`
- `rag`
- `web_search`
- `document_tool`
- `file_tool`
- `report_tool`

`PlanValidator` 会检查：

- `plan_type` 是否合法
- `tool_name` 是否存在
- `action_name` 是否存在
- 需要文件的 action 是否有文件
- Raman Pipeline 模板或步骤是否可用
- 深度学习占位算法是否 `available=false`

不存在的 tool/action 会触发回退旧流程。参数不合法或模型文件缺失会返回用户可读中文错误。

## Raman 自然语言映射

这些请求会优先进入增强规划层：

- “用 SG 平滑 + ALS 去基线 + z-score 归一化处理这个光谱”
  - `raman_pipeline.run_custom_pipeline`
  - 步骤：读取、校验、清理、排序、去重、SG、ALS、基线扣除、z-score

- “帮我看这个光谱质量怎么样”
  - `raman_pipeline.run_template_pipeline`
  - 模板：`quality_check`

- “找一下主要峰位并标出来”
  - `raman_pipeline.run_template_pipeline`
  - 模板：`peak_analysis`

- “用甲醇预测流程分析这个 CSV”
  - `hybrid`
  - 先运行 `raman_pipeline` 的 `methanol_prediction` 模板
  - 再调用 `raman_model.predict_methanol_concentration`

- “比较一下不同预处理方法对结果的影响”
  - `raman_pipeline.compare_pipelines`

- “先不要预测，只做预处理并画图”
  - `raman_pipeline.run_template_pipeline`
  - 模板：`basic_preprocessing`

- “用深度学习去噪”
  - `raman_pipeline.run_custom_pipeline`
  - 步骤中包含深度学习占位算法
  - 模型未配置时返回明确模型缺失/不可用原因

## Debug 行为

`debug=true` 时，响应会包含：

- `rule_intent`
- `llm_plan_raw`
- `validated_plan`
- `fallback_reason`

`debug=false` 时，响应中的 `debug` 为空对象，不暴露内部规划信息。

## 测试

推荐本项目 Windows 环境下使用轻量验证：

```powershell
python -B -c "import backend.main; print('ok')"
node --check frontend/app.js
```

mock planner 测试在 `tests/test_llm_planner_tool_schema.py` 中，不依赖外部模型。

