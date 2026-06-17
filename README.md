# RamanAgent

RamanAgent 正在向通用 Agent 形态演进，当前同时保留 Raman 光谱分析能力与通用大模型对话、Skill 调用、Workspace、Task Trace 等能力。

## 项目简介

这个项目主要用于处理上传的 Raman 光谱 CSV 文件，并给出面向甲醇分析场景的预测与解释结果。它既可以做专业分析，也可以像普通助手一样进行基础对话。

如果你想先了解当前的分层 Agent 设计，可以直接看 [ARCHITECTURE.md](./ARCHITECTURE.md)。

## 功能列表

- CSV 光谱上传
- 统一波数轴
- SG 平滑
- ALS 去基线
- CDAE 去噪
- CAE+ 基线估计
- SVR / RF 预测
- RamanAgent 对话
- 流式对话与 Agent 执行状态可视化
- 大模型平台与模型切换
- 历史记录
- 报告生成
- 光谱质量分析
- 多会话与 ChatGPT 风格侧边栏
- 会话文件 RAG、知识库 RAG、mixed RAG
- 知识库前端 CRUD、上传、绑定、重建索引
- OCR 可选 provider 与扫描件处理入口
- 文件转换与 PDF fallback 策略
- Raman Pipeline Builder：算法注册表、内置模板、自定义光谱处理链、步骤图谱和运行历史
- SQLite 统一持久化层与 Repository
- 异步任务中心：任务查询、取消、SSE 事件、产物查看
- Tool Schema 目录、Tool API、权限确认和审计日志
- 标准 Tool Runtime：统一参数校验、权限、Human Confirmation、超时、重试、错误码和审计
- Function Calling Adapter：OpenAI/Qwen/DeepSeek/generic schema 导出
- MCP Runtime 预留：配置读取、工具注册、unavailable 状态展示
- uploaded executable Skill 沙盒：路径、命令、环境变量和超时限制
- Raman Benchmark 测试集、Pipeline benchmark、候选模型训练与注册
- Docker Compose 本地/生产部署模板

## 项目结构

- `backend/`：后端 API、Agent 逻辑、模型服务、报告服务、工具函数
- `frontend/`：前端页面、样式和静态脚本
- `artifacts/`：模型文件、模型注册表、训练记录模板
- `outputs/`：运行产物，包括报告、图谱、上传文件和结果数据库
- `storage/`：统一数据库、任务记录、知识库、RAG 和用户状态
- `tests/`：自动化测试
- `docs/`：测试说明、部署补充说明等文档

## 环境准备

建议使用 Python 3.10 或 3.11。安装依赖前，先确保已经创建并激活虚拟环境。

在 Windows PowerShell 中可以这样做：

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

如果项目根目录使用的是其他依赖文件，请以仓库中的实际文件为准。

## 配置环境变量

先复制示例文件，再填写真实配置：

```powershell
Copy-Item .env.example .env
```

现在右上角的“模型列表”指的是大语言模型平台与模型切换，不再表示 Raman 训练模型。默认平台已经调整为 SenseNova。至少需要关注这些变量：

```env
LLM_PROVIDER=sensenova
LLM_MODEL=sensenova-6.7-flash-lite
SENSENOVA_API_KEY=
SENSENOVA_BASE_URL=https://token.sensenova.cn/v1
SENSENOVA_DEFAULT_MODEL=sensenova-6.7-flash-lite
SENSENOVA_AVAILABLE_MODELS=sensenova-6.7-flash-lite,deepseek-v4-flash

OPENAI_API_KEY=
OPENAI_BASE_URL=
OPENAI_DEFAULT_MODEL=
OPENAI_AVAILABLE_MODELS=

QWEN_API_KEY=
QWEN_BASE_URL=
QWEN_DEFAULT_MODEL=
QWEN_AVAILABLE_MODELS=

ZHIPU_API_KEY=
ZHIPU_BASE_URL=
ZHIPU_DEFAULT_MODEL=
ZHIPU_AVAILABLE_MODELS=

SILICONFLOW_API_KEY=
SILICONFLOW_BASE_URL=
SILICONFLOW_DEFAULT_MODEL=
SILICONFLOW_AVAILABLE_MODELS=

GEMINI_API_KEY=
GEMINI_BASE_URL=
GEMINI_DEFAULT_MODEL=
GEMINI_AVAILABLE_MODELS=

OLLAMA_BASE_URL=http://127.0.0.1:11434/v1
OLLAMA_DEFAULT_MODEL=qwen2.5:7b
OLLAMA_AVAILABLE_MODELS=qwen2.5:7b,qwen2.5:14b,qwen2.5-coder:7b,llama3.1:8b,deepseek-r1:7b

DATABASE_URL=sqlite:///storage/agent_memory.db
AGENT_RUNTIME_MODE=hybrid
LLM_PLANNER_MODE=hybrid
TOOL_CALLING_MODE=json
MCP_CONFIG_PATH=config/mcp_servers.json
MCP_RUNTIME_ENABLE=false
```

说明：

- `LLM_PROVIDER` / `LLM_MODEL`：全局默认平台与模型
- `*_DEFAULT_MODEL`：该平台的默认模型
- `*_AVAILABLE_MODELS`：前端平台内模型列表来源
- `*_API_KEY` / `*_BASE_URL`：平台连接配置
- 新代码会优先根据 `LLM_PROVIDER` 找到对应的 `*_BASE_URL` 和 `*_API_KEY`
- `LLM_BASE_URL` 仅作为旧代码兼容字段保留
- `DATABASE_URL`：统一持久化层数据库地址，默认 SQLite
- `AGENT_RUNTIME_MODE`：Agent 编排运行时，可选 `legacy/graph/hybrid`，默认 `hybrid`
- `LLM_PLANNER_MODE`：Planner 模式，可选 `off/mock/llm/hybrid`
- `TOOL_CALLING_MODE`：Planner function calling 模式，可选 `auto/native/json/off`，当前默认 JSON fallback
- `MCP_CONFIG_PATH`：MCP server 配置文件路径
- `MCP_RUNTIME_ENABLE`：是否启用真实 MCP runtime 连接；未启用时 MCP 工具显示为 unavailable

如果某个平台的 API Key 没有配置，前端仍会显示该平台和其模型，但会标记为“未配置”，并阻止实际切换调用。

RAG、Embedding、OCR、PDF 导出与生产部署配置见 [docs/production_readiness.md](./docs/production_readiness.md)。

## Windows 本地启动

先启动后端，再打开前端页面。

### 启动后端

```powershell
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

如果你想直接用脚本，也可以执行：

```powershell
.\scripts\start_backend.ps1
```

### 打开前端

后端启动后，在浏览器访问：

```text
http://127.0.0.1:8000/app/index.html
```

如果你把前端单独部署到静态服务器，也可以通过对应的前端地址访问。

## Docker 启动

```powershell
.\scripts\docker_up.ps1
```

开发模式：

```powershell
.\scripts\docker_up.ps1 --dev
```

更多说明见 [docs/deployment_docker.md](./docs/deployment_docker.md)。

## 后端接口

常用接口包括：

- `POST /api/agent/chat`
- `POST /api/agent/chat/stream`
- `POST /api/agent/analyze-file`
- `POST /api/files/upload`
- `POST /api/files/{file_id}/ocr`
- `POST /api/files/convert`
- `GET /api/workspaces/{conversation_id}/files`
- `GET /api/workspaces/{conversation_id}/context`
- `GET /api/knowledge-bases`
- `POST /api/knowledge-bases`
- `GET /api/knowledge-bases/{knowledge_base_id}/index-status`
- `POST /api/knowledge-bases/{knowledge_base_id}/rebuild-index`
- `GET /api/conversations/{conversation_id}/knowledge-bases`
- `POST /api/conversations/{conversation_id}/knowledge-bases`
- `DELETE /api/conversations/{conversation_id}/knowledge-bases/{knowledge_base_id}`
- `GET /api/rag/health`
- `POST /api/rag/rebuild-all`
- `GET /api/tools`
- `POST /api/tools/{tool_name}/{action_name}/validate`
- `POST /api/tools/{tool_name}/{action_name}/execute`
- `GET /api/agent/confirmations`
- `POST /api/agent/confirmations/{confirmation_id}/approve`
- `POST /api/agent/confirmations/{confirmation_id}/reject`
- `GET /api/mcp/status`
- `GET /api/mcp/servers`
- `GET /api/mcp/tools`
- `GET /api/raman/algorithms`
- `GET /api/raman/algorithms/{algorithm_id}`
- `GET /api/raman/pipeline/templates`
- `POST /api/raman/pipeline/validate`
- `POST /api/raman/pipeline/run`
- `GET /api/raman/pipeline/history`
- `GET /api/raman/datasets`
- `POST /api/raman/datasets`
- `POST /api/raman/benchmark/run`
- `POST /api/raman/training/run`
- `GET /api/raman/models`
- `POST /api/tasks`
- `GET /api/tasks/{task_id}/events`
- `POST /api/tasks/{task_id}/cancel`
- `GET /api/tasks/{task_id}/artifacts`
- `GET /api/audit-logs`
- `GET /api/tasks/{task_id}`
- `GET /api/conversations/{conversation_id}/tasks`
- `GET /api/conversations/{conversation_id}/messages`
- `GET /api/models/providers`
- `GET /api/models/providers/{provider_id}/models`
- `GET /api/models/current`
- `POST /api/models/select`
- `POST /api/models/refresh`
- `GET /api/raman-models`
- `GET /api/raman-models/current`
- `POST /api/methanol/predict-report`

## Raman Pipeline

新增的 Raman Pipeline 第一阶段提供可组合算法链，不替代旧甲醇预测主入口。用户可以在前端 `Pipeline` 面板中选择模板、添加算法、编辑参数 JSON、上传 CSV 后运行，并查看每一步状态、warning/error、中间图和最终图。

内置模板包括：

- `basic_preprocessing`
- `quality_check`
- `methanol_prediction`
- `peak_analysis`
- `deep_learning_placeholder`
- `ml_compare`

当前 ready 算法覆盖读取校验、波数轴、平滑、基线、归一化、峰检测、质量控制、基础特征提取和经典机器学习回归器。深度学习项为占位算法，模型文件缺失或推理适配器未接入时会标记 `available=false`，不会假装执行成功。

更多说明见 [docs/raman_pipeline.md](./docs/raman_pipeline.md) 和 [docs/algorithm_catalog.md](./docs/algorithm_catalog.md)。

## 产品化能力文档

- [统一持久化层](./docs/database_persistence.md)
- [异步任务中心](./docs/task_queue.md)
- [Tool Schema 标准](./docs/tool_schema_standard.md)
- [工具权限模型](./docs/tool_permission_model.md)
- [RAG 评测](./docs/rag_evaluation.md)
- [Raman Benchmark](./docs/raman_benchmark.md)
- [Raman 模型训练与注册](./docs/raman_model_training.md)
- [安全模型](./docs/security_model.md)
- [Skill 沙箱](./docs/skill_sandbox.md)
- [前端工作台](./docs/frontend_workbench.md)
- [Agent Graph Runtime](./docs/agent_graph_runtime.md)
- [Function Calling Adapter](./docs/function_calling_adapter.md)
- [MCP 接入预留](./docs/mcp_integration.md)
- [RamanSPy Adapter](./docs/ramanspy_adapter.md)
- [Agent Eval](./docs/agent_evaluation.md)

## 流式对话

前端默认优先调用 `POST /api/agent/chat/stream`，通过 `fetch + ReadableStream` 读取 SSE 事件；如果流式接口不可用，会自动回退旧的 `POST /api/agent/chat`。旧接口保持兼容。

流式事件包括：

- `start`：请求已进入 Agent。
- `status`：消息整理、意图判断等可见状态。
- `planner`：规则路由、增强 Planner 或旧 Planner 的公开摘要。
- `tool_start` / `tool_progress` / `tool_result`：工具、Skill、Raman Pipeline 执行状态。
- `delta`：助手回答增量。
- `final`：最终统一响应。
- `error`：用户可理解的错误。
- `done`：流结束。

更多说明见 [docs/streaming_chat.md](./docs/streaming_chat.md)。

## Workspace 与任务追踪

通用 Agent 会为每个会话创建独立工作区：

```text
workspace/{user_id}/{conversation_id}/
├── uploads/
├── outputs/
├── logs/
│   ├── messages.jsonl
│   ├── task_steps.jsonl
│   ├── skill_runs.jsonl
│   └── errors.jsonl
├── context/
│   ├── context_summary.md
│   ├── active_files.json
│   ├── task_state.json
│   └── memory_snapshot.json
└── workspace_meta.json
```

当前会话上下文保存在 workspace 中。长期用户记忆单独保存在 `storage/users/{user_id}/memory.json`，不会混进单个 conversation workspace。

## 运行验证

本项目在 Windows 沙箱环境下默认不要直接运行 `pytest`。推荐先做导入和语法检查：

```powershell
python -B -c "import backend.main; print('ok')"
node --check frontend/app.js
.\scripts\smoke_check.ps1
```

如果后续你确实需要完整测试，再单独执行项目里的测试脚本或完整测试命令。

这次 Tool Runtime 相关的窄测试：

```powershell
python -m pytest tests/test_tool_schema_contract.py
python -m pytest tests/test_function_calling_adapter.py
python -m pytest tests/test_mcp_config.py
python -m pytest tests/test_human_confirmation.py
python -m pytest tests/test_audit_logs.py
python -m pytest tests/test_error_codes.py
```

## 运行时文档

- [docs/agent_graph_runtime.md](./docs/agent_graph_runtime.md)
- [docs/tool_runtime.md](./docs/tool_runtime.md)
- [docs/function_calling_adapter.md](./docs/function_calling_adapter.md)
- [docs/mcp_runtime.md](./docs/mcp_runtime.md)
- [docs/human_confirmation.md](./docs/human_confirmation.md)
- [docs/audit_logs.md](./docs/audit_logs.md)
- [docs/error_codes.md](./docs/error_codes.md)
- [docs/skill_sandbox.md](./docs/skill_sandbox.md)

## 常见问题

### LLM API Key 无效

检查 `.env` 中对应供应商的 API Key 是否填写正确，尤其是 `OPENAI_API_KEY`、`QWEN_API_KEY`、`ZHIPU_API_KEY`、`SILICONFLOW_API_KEY`、`GEMINI_API_KEY`。

### 联网搜索不可用

如果你要使用正式的联网搜索 Skill，请检查下面这些变量：

```env
WEB_SEARCH_ENABLED=true
WEB_SEARCH_PROVIDER=tavily
WEB_SEARCH_MAX_RESULTS=5
WEB_SEARCH_TIMEOUT_SECONDS=20
WEB_SEARCH_REQUIRE_CITATIONS=true
WEB_SEARCH_FALLBACK_PROVIDER=duckduckgo

TAVILY_API_KEY=你的 Tavily API Key
TAVILY_SEARCH_DEPTH=basic
TAVILY_INCLUDE_ANSWER=false
TAVILY_INCLUDE_RAW_CONTENT=false
TAVILY_INCLUDE_IMAGES=false
```

默认情况下，普通聊天不会自动联网；只有用户明确要求联网查找最新信息，或系统路由判断需要联网搜索时，才会启用 `web-search` skill。

### 模型文件缺失

确认 `artifacts/` 下的模型目录和 `model_registry.json` 是否完整。若仍使用旧结构，请检查根目录旧模型文件是否保留。

### “模型列表”入口变更

现在右上角的“模型列表”按钮对应的是大语言模型切换面板，先选平台，再选该平台下的模型，默认平台为 SenseNova。

如果你要查看或管理 Raman 训练出来的分类/回归模型，请使用 `GET /api/raman-models` 和 `GET /api/raman-models/current`。它们仍然保留，用于光谱分析链路，不会再和聊天大模型混在一起。

### CSV 格式不对

确保上传的是有效的光谱 CSV 文件，且包含项目要求的波数和强度数据。

### 端口被占用

如果 `8000` 端口已被占用，可以改用其他端口，例如：

```powershell
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8001 --reload
```

### 前端访问不到后端

确认后端已启动，并且前端访问地址与后端端口一致。

## 安全提醒

- 不要提交 `.env`
- 不要提交 `outputs/` 下的运行产物
- 不要提交 `storage/` 下的知识库、向量库、文件索引
- 不要公开真实样品数据
- 不要把 API Key 写入代码、README 或测试

演示流程见 [docs/demo_script.md](./docs/demo_script.md)。

## Docker

当前仓库未新增 `Dockerfile` 和 `docker-compose.yml`。

原因是项目已经可以通过 Windows 本地 Python + Uvicorn 直接启动，继续保持轻量化更利于维护；如果后续需要容器化部署，可以再单独补充，不影响现有代码结构。

## MVP 第二阶段

二阶段新增的用户系统、项目中心、报告导出、批量分析说明见：

- [docs/mvp_phase_2.md](./docs/mvp_phase_2.md)
