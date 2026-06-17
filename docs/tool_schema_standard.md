# Tool Schema 标准

## 目标

Tool Schema 用来让 Planner、Tool API 和前端共享同一份工具能力描述。

核心文件：

- `backend/agent/planning/tool_schema.py`
- `backend/agent/planning/tool_catalog.py`
- `backend/api/tool_api.py`

## Tool 字段

每个工具包含：

- `name`
- `display_name`
- `description`
- `category`
- `version`
- `owner`
- `source`
- `enabled`
- `available`
- `unavailable_reason`
- `danger_level`
- `requires_auth`
- `requires_file`
- `permissions`
- `examples`
- `input_schema`
- `output_schema`
- `actions`

## Action 字段

每个动作包含：

- `name`
- `display_name`
- `description`
- `input_schema`
- `output_schema`
- `required_args`
- `default_args`
- `examples`
- `requires_file`
- `requires_confirmation`
- `confirmation_message`
- `danger_level`
- `timeout_seconds`
- `retry_policy`
- `permissions`
- `side_effects`
- `visible_to_user`
- `supports_streaming`
- `supports_async_task`

`side_effects` 必须来自固定集合：

- `none`
- `read_file`
- `write_file`
- `network`
- `execute_code`
- `delete_file`
- `modify_project`
- `modify_model`
- `cost_money`
- `long_running`

`execute_code/delete_file/modify_model/cost_money` 等高风险副作用必须配合足够的 `danger_level` 和确认机制。

## Tool API

```text
GET /api/tools
GET /api/tools/{tool_name}
GET /api/tools/{tool_name}/actions
POST /api/tools/{tool_name}/{action_name}/validate
POST /api/tools/{tool_name}/{action_name}/execute
```

需要确认的动作会先返回 `CONFIRMATION_REQUIRED` 和 `confirmation_payload`。批准后可传入 `confirmation_id` 或兼容字段 `confirmed=true`。

## 标准执行层

Tool API 的执行入口已经接入 [tool_runtime.md](./tool_runtime.md)，所有工具执行统一经过参数校验、权限校验、确认、超时、重试、审计和错误码归一化。
