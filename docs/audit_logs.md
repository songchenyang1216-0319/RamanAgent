# Audit Logs

工具执行、确认请求和确认决策都会写入审计日志。目标是让 Tool Runtime 可追踪、可审计、可回放分析。

## 记录内容

Tool Runtime 会记录：

- `tool.confirmation_required`
- `tool.execute.start`
- `tool.execute.finish`
- `tool.execute.error`

Confirmation API 会记录：

- `tool.confirmation.approve`
- `tool.confirmation.reject`

日志字段包括：

- `user_id`
- `action`
- `resource_type`
- `resource_id`
- `ip_address`
- `user_agent`
- `detail`

## 脱敏规则

`backend/tool_runtime/tool_audit.py` 会递归脱敏这些 key：

- `api_key`
- `secret`
- `token`
- `password`
- `authorization`
- `.env`

长字段会截断，避免把大文件内容或长日志写入数据库。

## 查询

现有审计接口继续使用：

```text
GET /api/audit-logs
```

前端“审计”面板会读取该接口。

## 测试

```powershell
python -m pytest tests/test_audit_logs.py
```
