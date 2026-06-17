# Agent Graph Runtime

RamanAgent 的 Graph Runtime 是旧 `AgentOrchestrator` 之上的增强层，用显式 `GraphState` 和节点状态机替代继续在 Orchestrator 中堆叠 if/else。旧 IntentRouter、Planner 和 Orchestrator 仍保留为 fallback。

## 为什么升级

旧编排把标准化、上下文读取、意图识别、Planner、校验、执行、RAG、Skill、流式事件和响应封装都放在一个类里。Graph Runtime 把这些步骤拆成可观察节点，让每一步都有公开状态摘要、debug trace 和错误收口。

## 配置

```env
AGENT_RUNTIME_MODE=hybrid
LLM_PLANNER_MODE=hybrid
```

`AGENT_RUNTIME_MODE` 可选：

- `legacy`：完全走旧 Orchestrator。
- `graph`：优先走 Graph Runtime，失败返回 graph error。
- `hybrid`：默认值。先走 Graph Runtime，失败或请求 fallback 时回退旧 Orchestrator。

`LLM_PLANNER_MODE` 可选 `off/mock/llm/hybrid`，由现有 `LLMPlanner` 读取。

## GraphState 字段

核心字段包括：

- `request_payload`
- `normalized_message`
- `conversation_id`
- `session_id`
- `user_id`
- `message`
- `files`
- `intent`
- `plan`
- `validated_plan`
- `execution_results`
- `observations`
- `repair_attempts`
- `requires_confirmation`
- `confirmation_message`
- `final_response`
- `stream_events`
- `debug`
- `errors`
- `started_at`
- `elapsed_ms`

`debug=false` 时不会向前端返回 node trace、LLM planner raw 等调试细节，只输出用户可见状态摘要。

## 节点职责

- `NormalizeNode`：调用 `MessageNormalizer`。
- `ContextNode`：读取 workspace、active files、memory、task state；失败只记录 warning。
- `IntentNode`：调用规则路由并判断是否应走旧高置信路径。
- `PlannerNode`：按 `LLM_PLANNER_MODE` 调用 `LLMPlanner` 或旧 `Planner`。
- `ValidateNode`：调用 `PlanValidator`，危险动作转为确认问题。
- `ExecuteNode`：只执行验证后的增强计划；旧可信计划走 legacy executor。
- `ObserveNode`：归类为 success、recoverable_error、fatal_error、need_user_input。
- `RepairNode`：最多自动修复一次，例如 SG window_length、RAG 无知识库提示、深度学习模型缺失建议。
- `HumanConfirmNode`：高风险动作生成确认问题，不直接执行。
- `FinalAnswerNode`：调用 `ResponseBuilder` 生成统一 `AgentResponse`。

## 流式事件

Graph Runtime 不新增前端必须识别的事件类型，而是映射到现有事件：

- `start`
- `status`
- `planner`
- `tool_start`
- `tool_progress`
- `tool_result`
- `delta`
- `final`
- `error`
- `done`

前端可显示“正在整理上下文”“正在生成计划”“正在校验工具参数”“正在执行工具”“正在观察结果”“正在修复错误”“正在生成最终回答”。

## 测试

```powershell
python -B -c "import backend.main; print('ok')"
python -m pytest tests/test_agent_graph_runtime.py
python -m pytest tests/test_graph_runner_stream.py
```
