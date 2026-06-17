# Agent Evaluation

Agent Eval 用于评估 Agent 路由、工具选择、算法选择、fallback、修复和澄清行为。

## 目录

```text
backend/evaluation/agent_eval/
  dataset_schema.py
  evaluator.py
  metrics.py
  run.py
```

测试数据：

```text
tests/fixtures/agent_eval_cases.json
```

覆盖场景包括普通聊天、当前模型查询、Raman 质量检查、峰位分析、自定义 Pipeline、RAG 问答、Web Search、文件转换、报告生成、缺文件澄清和非法工具调用。

## 指标

- `intent_accuracy`
- `route_accuracy`
- `tool_selection_accuracy`
- `algorithm_selection_accuracy`
- `fallback_rate`
- `repair_rate`
- `clarification_rate`
- `error_rate`

## 运行

```powershell
python -m backend.evaluation.agent_eval.run --dataset tests/fixtures/agent_eval_cases.json
```
