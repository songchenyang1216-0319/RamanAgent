# Human Confirmation

Human Confirmation 用于阻止高风险工具被自动执行。它只展示执行状态摘要，不暴露隐藏思维链。

## 哪些操作需要确认

`ToolCatalog` 中满足任一条件会触发确认：

- `requires_confirmation=true`
- `danger_level=high`
- `danger_level=critical`

典型动作：

- 删除文件
- 执行 uploaded Skill
- 重建索引
- 取消任务
- 切换模型
- 批量或高成本任务

## 后端流程

```text
ToolRuntime.execute
  -> needs_confirmation
  -> create_confirmation
  -> 返回 ToolResult(status=confirmation_required)
```

返回中包含：

- `requires_confirmation=true`
- `error_code=CONFIRMATION_REQUIRED`
- `confirmation_payload.confirmation_id`
- `confirmation_payload.message`
- `confirmation_payload.danger_level`

## API

- `GET /api/agent/confirmations`
- `GET /api/agent/confirmations/{confirmation_id}`
- `POST /api/agent/confirmations/{confirmation_id}/approve`
- `POST /api/agent/confirmations/{confirmation_id}/reject`

批准后，调用工具时可传：

```json
{
  "args": {
    "confirmation_id": "..."
  }
}
```

或继续兼容旧字段：

```json
{
  "confirmed": true
}
```

## 前端展示

前端会在 Agent Trace 或工具目录中展示确认卡片：

- 工具名
- action
- 风险等级
- 后端确认文案
- 批准/拒绝按钮

批准不会自动重放隐藏步骤。用户可以重新发送请求，或工具调用方携带 `confirmation_id` 继续执行。

## 测试

```powershell
python -m pytest tests/test_human_confirmation.py
```
