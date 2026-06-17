# MCP Integration

本阶段只做 MCP 预留，不强制连接真实 MCP Server。更完整的运行时说明见 [mcp_runtime.md](./mcp_runtime.md)。

## 配置

默认读取：

```text
config/mcp_servers.json
```

仓库提供示例：

```text
config/mcp_servers.example.json
```

也可以通过环境变量指定：

```env
MCP_CONFIG_PATH=path/to/mcp_servers.json
```

示例：

```json
{
  "servers": [
    {
      "name": "docs",
      "transport": "stdio",
      "enabled": true,
      "command": "python",
      "args": ["server.py"],
      "timeout_seconds": 30,
      "tools": [
        {
          "name": "search",
          "description": "Search internal docs",
          "input_schema": {
            "type": "object",
            "properties": {
              "query": { "type": "string" }
            },
            "required": ["query"]
          }
        }
      ]
    }
  ]
}
```

## 行为

- 配置不存在时 `MCPClient.status().available=false`。
- MCP tool 可转换成 `ToolSpec`。
- `ToolCatalog` 会加载配置中声明的 MCP 工具，并用 `owner=mcp:<server>` 标记来源。
- 默认未启用真实连接时，MCP 工具显示为 `available=false`。
- 执行不可用 MCP 工具时返回 `MCP_SERVER_UNAVAILABLE`，不抛异常导致 Agent 崩溃。

## API

- `GET /api/mcp/status`
- `GET /api/mcp/servers`
- `GET /api/mcp/tools`
