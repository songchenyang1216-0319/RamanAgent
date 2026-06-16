# 流式对话与 Agent 执行状态

本阶段把 RamanAgent 的普通请求-响应式聊天扩展为流式聊天，同时保留旧接口兼容。

## 接口

旧接口仍然可用：

```text
POST /api/agent/chat
```

新流式接口：

```text
POST /api/agent/chat/stream
Content-Type: application/json 或 multipart/form-data
Accept: text/event-stream
```

JSON 示例：

```json
{
  "message": "用 SG 平滑 + ALS 去基线 + z-score 归一化处理这个光谱",
  "session_id": "optional-session-id",
  "debug": false
}
```

文件上传沿用旧接口的 FormData 字段：`message`、`file` / `files`、`session_id`、`conversation_id`、`provider_id`、`model_id`、`debug` 等。

## AgentStreamEvent

后端事件结构定义在 `backend/schemas/agent_stream.py`：

```json
{
  "event": "status",
  "conversation_id": "...",
  "session_id": "...",
  "message_id": null,
  "task_id": null,
  "sequence": 2,
  "timestamp": "2026-06-12T00:00:00+00:00",
  "content": "正在判断任务类型。",
  "data": {},
  "visible": true
}
```

## 事件类型

- `start`：请求进入 Agent。
- `status`：消息整理、上下文读取、回退等公开状态。
- `planner`：规则路由、LLM Planner、PlanValidator 或旧 Planner 的公开摘要。
- `tool_start`：即将执行工具、Skill 或 Pipeline。
- `tool_progress`：工具执行中的步骤状态。Raman Pipeline 会尽量输出算法步骤、warning、error 和 artifacts。
- `tool_result`：工具执行完成。
- `delta`：助手回答增量。
- `final`：最终统一 `AgentResponse`，位于 `data.response`。
- `error`：用户可见错误。
- `done`：流结束。

## 前端行为

前端 `frontend/app.js` 默认优先调用 `sendAgentChatStream()`：

1. 先追加用户消息和上传文件卡片。
2. 创建助手气泡，气泡内部包含执行轨迹区和回答区。
3. 使用 `fetch` + `ReadableStream` 解析 SSE。
4. `delta` 写入回答区。
5. `planner/tool_* /error/done` 写入轨迹区。
6. 用户点击“停止”时通过 `AbortController` 中断请求。
7. 如果流式请求在收到任何事件前失败，自动回退旧 `/api/agent/chat`。

## 大模型流式策略

`backend/services/llm_service.py` 新增：

- `generate_general_reply_stream`
- `stream_general_reply`

当 provider 可用时优先尝试 OpenAI-compatible `stream=True`；如果不支持、配置缺失或调用失败，则调用旧 `generate_general_reply()`，再按中文 2-8 字、英文词块模拟流式输出。

## 兼容性

- 旧 `/api/agent/chat` 未删除，仍返回普通 JSON。
- 旧 IntentRouter、Planner、Skill/Tool runner 未删除。
- 流式 Orchestrator 复用同一套路由、Planner、PlanValidator、PlanExecutor 和 ResponseBuilder。
- `debug=false` 时不暴露内部调试信息；`debug=true` 时 final 响应和 planner 事件会包含规则路由、LLM plan raw、校验结果和回退原因。

## 手动测试

```powershell
python -B -c "import backend.main; print('ok')"
node --check frontend/app.js
node --check frontend/js/api.js
```

SSE 快速检查：

```powershell
python -B -c "from fastapi.testclient import TestClient; from backend.main import app; c=TestClient(app); r=c.post('/api/agent/chat/stream', json={'message':'你好'}); print(r.text[:500])"
```
