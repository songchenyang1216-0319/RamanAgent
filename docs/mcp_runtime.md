# MCP Runtime

本阶段 MCP 是预留运行时：支持配置读取、工具注册、ToolCatalog 展示和明确的 unavailable 状态；暂不强制连接真实 MCP Server。

## 配置文件

默认读取：

```text
config/mcp_servers.json
```

可以复制示例：

```powershell
Copy-Item config\mcp_servers.example.json config\mcp_servers.json
```

也可以通过环境变量覆盖：

```env
MCP_CONFIG_PATH=D:\path\to\mcp_servers.json
```

## 配置结构

```json
{
  "servers": [
    {
      "name": "local_demo",
      "transport": "stdio",
      "command": "python",
      "args": ["server.py"],
      "enabled": true,
      "timeout_seconds": 30,
      "tools": [
        {
          "name": "demo_lookup",
          "description": "Example MCP tool",
          "input_schema": {
            "type": "object",
            "properties": {
              "query": {"type": "string"}
            },
            "required": ["query"]
          }
        }
      ]
    }
  ]
}
```

## API

- `GET /api/mcp/status`
- `GET /api/mcp/servers`
- `GET /api/mcp/tools`

## ToolCatalog 展示

MCP tool 会转换为 `ToolSpec`：

- `source=mcp`
- `owner=mcp:{server_name}`
- `tool_name=mcp_{server}_{tool}`
- 默认 action 为 `call`

当前没有启用真实连接时，MCP 工具会显示为 `available=false`，执行返回 `MCP_SERVER_UNAVAILABLE`，不会导致 Agent 主流程崩溃。

## 测试

```powershell
python -m pytest tests/test_mcp_config.py
python -m pytest tests/test_mcp_tool_adapter.py
```
