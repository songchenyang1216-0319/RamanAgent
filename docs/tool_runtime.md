# Tool Runtime

`backend/tool_runtime/` 是 RamanAgent 的标准工具执行层。它不是推翻旧 Tool/Skill/RAG/Raman，而是在旧能力外面增加统一入口。

## 入口

- 代码入口：`ToolRuntime.execute(tool_name, action_name, args, context)`
- API 入口：`POST /api/tools/{tool_name}/{action_name}/execute`
- Planner 入口：`PlanExecutor` 会把验证后的计划 step 交给 `ToolRuntime`

`ToolContext` 统一携带：

- `user_id`
- `conversation_id`
- `session_id`
- `workspace_id`
- `file_ids`
- `active_files`
- `request_id`
- `task_id`
- `debug`
- `permissions`
- `source`
- `ip_address`
- `user_agent`
- `metadata`

## 执行流程

```text
ToolRuntime.execute
  -> ToolCatalog 查找 tool/action
  -> input_schema / required_args 校验
  -> 权限校验
  -> 文件作用域校验
  -> 高风险操作生成 ConfirmationRequest
  -> 写入 tool.execute.start 审计
  -> timeout + retry 包装 adapter
  -> 写入 tool.execute.finish 或 tool.execute.error 审计
  -> 返回 ToolResult
```

## Adapter

- `BuiltinToolAdapter`：包装 `file_tool`、`model_tool`
- `RamanToolAdapter`：包装 Raman Pipeline 与甲醇模型
- `RAGToolAdapter`：包装 RAG 问答
- `SkillToolAdapter`：包装 Web Search、文档、报告、Skill 执行
- `MCPRuntimeToolAdapter`：包装 MCP 工具预留入口
- `TaskToolAdapter`：包装任务查询

## 安全边界

- LLM 输出不会直接执行，必须经过 `PlanValidator`
- 高风险 action 必须先返回 `CONFIRMATION_REQUIRED`
- uploaded executable Skill 继续通过 Skill 沙盒执行
- 审计日志会脱敏 `api_key`、`token`、`secret`、`password`

## 测试

```powershell
python -m pytest tests/test_tool_schema_contract.py
python -m pytest tests/test_human_confirmation.py
python -m pytest tests/test_audit_logs.py
python -m pytest tests/test_error_codes.py
```
