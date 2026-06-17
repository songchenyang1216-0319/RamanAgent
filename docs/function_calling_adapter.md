# Function Calling Adapter

`backend/agent/planning/function_calling_adapter.py` 负责把现有 `ToolSpec` / `ActionSpec` 导出为不同 provider 可理解的函数 schema。

## 支持格式

- OpenAI-compatible function schema
- Qwen-compatible function schema
- DeepSeek-compatible function schema
- generic JSON schema

示例：

```python
from backend.agent.planning import FunctionCallingAdapter, ToolCatalog

tool = ToolCatalog().get("raman_pipeline")
action = tool.get_action("run_template_pipeline")
schema = FunctionCallingAdapter.to_openai_function(tool, action, strict=True)
```

strict 模式会设置 `additionalProperties=false`，并保留 action 的 `required_args`。

## 批量导出

```python
catalog = ToolCatalog()
openai_tools = FunctionCallingAdapter.to_openai_tools(catalog, strict=True)
qwen_tools = FunctionCallingAdapter.to_qwen_tools(catalog)
deepseek_tools = FunctionCallingAdapter.to_deepseek_tools(catalog)
generic = FunctionCallingAdapter.to_generic_json_schema(catalog, strict=True)
```

函数名格式统一为：

```text
{tool_name}__{action_name}
```

可通过 `FunctionCallingAdapter.from_function_name(name)` 解析回 `tool_name/action_name`。

## Provider Tool Calls 解析

`parse_tool_calls(provider_response)` 支持解析 OpenAI-compatible 的：

- `message.tool_calls`
- `choices[0].message.tool_calls`
- 直接传入 tool_calls list

解析结果为 `FunctionToolCall`，包含：

- `id`
- `name`
- `arguments`
- `provider`

## 并行 Tool Calls

Adapter 已提供并行 tool calls 的数据结构：

```python
FunctionCallingAdapter.parallel_tool_calls([...])
```

当前执行层仍可先串行执行，后续 provider 支持原生 function calling 时再逐步接入。

## Planner 接入

`LLMPlanner` 读取：

```env
TOOL_CALLING_MODE=auto|native|json|off
```

当前阶段：

- `json`：默认 JSON plan。
- `auto/native`：在 prompt 中附带 OpenAI-compatible tools schema，但仍允许 JSON fallback。
- `off`：不强制使用 function calling。

无论哪种模式，LLM 输出都不会直接执行，仍然必须经过 `PlanValidator` 与 `ToolRuntime`。
