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
- 大模型平台与模型切换
- 历史记录
- 报告生成
- 光谱质量分析

## 项目结构

- `backend/`：后端 API、Agent 逻辑、模型服务、报告服务、工具函数
- `frontend/`：前端页面、样式和静态脚本
- `artifacts/`：模型文件、模型注册表、训练记录模板
- `outputs/`：运行产物，包括报告、图谱、上传文件和结果数据库
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
```

说明：

- `LLM_PROVIDER` / `LLM_MODEL`：全局默认平台与模型
- `*_DEFAULT_MODEL`：该平台的默认模型
- `*_AVAILABLE_MODELS`：前端平台内模型列表来源
- `*_API_KEY` / `*_BASE_URL`：平台连接配置
- 新代码会优先根据 `LLM_PROVIDER` 找到对应的 `*_BASE_URL` 和 `*_API_KEY`
- `LLM_BASE_URL` 仅作为旧代码兼容字段保留

如果某个平台的 API Key 没有配置，前端仍会显示该平台和其模型，但会标记为“未配置”，并阻止实际切换调用。

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

## 后端接口

常用接口包括：

- `POST /api/agent/chat`
- `POST /api/agent/analyze-file`
- `POST /api/files/upload`
- `GET /api/workspaces/{conversation_id}/files`
- `GET /api/workspaces/{conversation_id}/context`
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
```

如果后续你确实需要完整测试，再单独执行项目里的测试脚本或完整测试命令。

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
- 不要公开真实样品数据
- 不要把 API Key 写入代码、README 或测试

## Docker

当前仓库未新增 `Dockerfile` 和 `docker-compose.yml`。

原因是项目已经可以通过 Windows 本地 Python + Uvicorn 直接启动，继续保持轻量化更利于维护；如果后续需要容器化部署，可以再单独补充，不影响现有代码结构。
