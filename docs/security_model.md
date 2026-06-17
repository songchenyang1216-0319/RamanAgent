# 安全模型

## 认证

生产环境设置：

```env
APP_ENV=production
```

后端会要求显式登录 token。开发环境保留默认用户兼容旧流程。

## 权限

权限判断集中在：

- `backend/api/auth_dependencies.py`
- `backend/security/permissions.py`
- `backend/tool_runtime/tool_permissions.py`

管理员可查看审计日志和执行全量 RAG 重建。普通用户只能访问自己的项目、文件、任务和报告。

Tool Runtime 会把 `ToolContext.permissions`、用户角色和 Tool/Action 上的 `permissions` 合并校验。

## Human Confirmation

高风险工具不会直接执行，会先返回确认请求：

- 删除文件
- uploaded Skill 执行
- 切换模型
- 重建索引
- 取消任务

接口见 [human_confirmation.md](./human_confirmation.md)。

## 审计

审计写入：

```text
audit_logs
```

当前覆盖：

- Tool Runtime 执行 start/finish/error
- Tool confirmation approve/reject
- Raman Pipeline 运行
- 部分异步任务创建

Tool Runtime 审计会脱敏 `api_key/token/secret/password/authorization`。详情见 [audit_logs.md](./audit_logs.md)。

## 文件安全

文件下载、预览和 OCR 会检查路径是否仍在项目根目录下，避免路径穿越。

Skill 沙盒还会使用 `SandboxPolicy`、`path_guard`、`command_guard` 限制 uploaded executable Skill。详情见 [skill_sandbox.md](./skill_sandbox.md)。

## 错误码

工具执行统一返回 `error_code/error_message`，不会把内部异常原样抛给前端。详情见 [error_codes.md](./error_codes.md)。

## 密钥

`.env.example` 只能使用占位值。`scripts/check_env_safety.py` 会在 smoke 检查中验证示例配置。
