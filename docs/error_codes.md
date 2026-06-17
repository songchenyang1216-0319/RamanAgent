# Tool Error Codes

Tool Runtime 统一使用 `error_code + error_message` 返回可读错误。前端可以直接展示 `error_message`，也可以根据 `error_code` 做卡片和引导。

## 当前错误码

- `TOOL_NOT_FOUND`
- `ACTION_NOT_FOUND`
- `INVALID_ARGUMENTS`
- `PERMISSION_DENIED`
- `CONFIRMATION_REQUIRED`
- `CONFIRMATION_REJECTED`
- `CONFIRMATION_NOT_FOUND`
- `CONFIRMATION_APPROVED`
- `TOOL_UNAVAILABLE`
- `TOOL_TIMEOUT`
- `SANDBOX_VIOLATION`
- `MCP_SERVER_UNAVAILABLE`
- `MCP_TOOL_FAILED`
- `MODEL_UNAVAILABLE`
- `MODEL_API_ERROR`
- `RAG_INDEX_UNAVAILABLE`
- `RAG_NO_CONTEXT`
- `RAMAN_FILE_INVALID`
- `RAMAN_PIPELINE_FAILED`
- `SKILL_EXECUTION_FAILED`
- `TASK_CANCELLED`
- `UNKNOWN_ERROR`

## 分类策略

`ToolRuntimeException` 会保留明确错误码；未知错误会被归一化为 `UNKNOWN_ERROR`。

`classify_exception` 会把常见异常映射为：

- `TimeoutError` -> `TOOL_TIMEOUT`
- `PermissionError` -> `PERMISSION_DENIED`
- 沙盒文本 -> `SANDBOX_VIOLATION`
- MCP 文本 -> `MCP_TOOL_FAILED`
- RAG 上下文不足 -> `RAG_NO_CONTEXT`
- Raman/Pipeline 文本 -> `RAMAN_PIPELINE_FAILED`

## 测试

```powershell
python -m pytest tests/test_error_codes.py
```
