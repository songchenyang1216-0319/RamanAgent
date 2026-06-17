# 工具权限模型

## 角色

当前角色定义在 `backend/security/permissions.py`：

- `admin`
- `project_owner`
- `project_editor`
- `user`
- `project_viewer`

## 风险等级

Tool 和 Action 都带有 `danger_level`：

- `safe`：无副作用
- `low`：只读或轻量查询
- `medium`：会触发计算、索引或生成产物
- `high`：会删除、覆盖或产生明显副作用
- `critical`：高成本或高破坏性操作

## 权限校验

Tool 和 Action 可声明 `permissions`。`ToolRuntime` 会检查：

- 当前用户角色对应权限
- `ToolContext.permissions`
- namespace 通配符，例如 `project:*`

管理员角色拥有 `*`。

## 确认规则

`requires_confirmation=true`、`danger_level=high` 或 `danger_level=critical` 的动作会先生成确认请求。用户批准后可以传入 `confirmation_id`，旧调用仍兼容 `confirmed=true`。

接口见 [human_confirmation.md](./human_confirmation.md)。

## 审计

直接 Tool API 与 Planner 执行都会通过 Tool Runtime 写入审计日志：

```text
GET /api/audit-logs
```

生产环境下审计接口仅管理员可读。
