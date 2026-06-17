# 生产部署与能力检查清单

## 必填安全项

- `.env` 不要提交，`.gitignore` 已忽略 `.env`、`.env.*`、`storage/`、`outputs/`。
- `.env.example` 只能放占位值，例如 `your_openai_api_key`，不要放真实 key。
- 生产环境设置 `APP_ENV=production` 后，接口默认要求显式登录 token。
- 不要开启过宽的 debug 输出；前端普通模式不会展示内部 debug。
- 高风险工具动作必须走 `requires_confirmation`，直接 Tool API 会写审计日志。
- 上传 Skill 的可执行脚本会通过 `backend/security/skill_sandbox.py` 限制路径、剥离敏感环境变量并设置超时。

## 数据库与任务中心

默认 SQLite：

```env
DATABASE_URL=sqlite:///storage/agent_memory.db
TASK_QUEUE_BACKEND=local
TASK_QUEUE_WORKERS=2
```

启动时会初始化统一表结构，任务中心写入 `tasks` 和 `task_steps`。长任务优先使用 `async_task=true`，再通过任务中心查看状态、事件和产物。

## RAG / Embedding

- 开发环境可以使用：

```env
VECTOR_DB_PROVIDER=mock
EMBEDDING_PROVIDER=mock
```

- 生产环境建议使用：

```env
VECTOR_DB_PROVIDER=chroma
VECTOR_DB_DIR=storage/vector_db
EMBEDDING_PROVIDER=local
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
```

- 如果使用远程 embedding：

```env
EMBEDDING_PROVIDER=remote
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_API_KEY=your_embedding_api_key
EMBEDDING_BASE_URL=https://api.openai.com/v1
EMBEDDING_TIMEOUT_SECONDS=30
EMBEDDING_BATCH_SIZE=64
```

- 健康检查：

```text
GET /api/rag/health?conversation_id=<conversation_id>
GET /api/rag/status?conversation_id=<conversation_id>
```

## mixed RAG rerank

默认关闭 rerank，打开方式：

```env
RAG_ENABLE_RERANK=true
RAG_RERANK_PROVIDER=lexical
RAG_MIXED_MIN_PER_SOURCE=1
```

当前内置 reranker 是轻量 lexical rerank，会结合向量分和关键词重叠，并在 mixed RAG 中保留当前会话文件和知识库两类来源。

## OCR

配置项：

```env
OCR_PROVIDER=auto
OCR_LANGUAGE=eng+chi_sim
OCR_MAX_PAGES=10
```

- `none`：关闭 OCR。
- `auto` / `pytesseract`：使用 `pytesseract`。
- `paddleocr`：预留 PaddleOCR，未安装时会明确提示。

PDF OCR 需要额外安装 `pdf2image` 和本机 Poppler；缺失时接口会返回明确错误，不会假装识别成功。

## PDF 导出

配置项：

```env
PDF_EXPORT_PROVIDER=none
```

- `none` / `html`：生成 HTML fallback，并返回 `pdf_export_available=false`。
- `weasyprint`：使用 WeasyPrint。
- `playwright`：使用 Playwright Chromium。
- `auto`：依次尝试 WeasyPrint、Playwright，失败后回退 HTML。

## Smoke Check

Windows PowerShell：

```powershell
.\scripts\smoke_check.ps1
```

它会执行：

- `.env.example` 安全检查
- RAG/embedding/rerank smoke test
- `backend.main` 导入检查
- FastAPI health/chat/stream/algorithm/template/tool smoke test
- 前端 JS 语法检查

## Docker

```powershell
.\scripts\docker_up.ps1
```

默认 compose 会挂载 `storage`、`outputs`、`artifacts` 和 `data`，避免容器重建丢失模型文件和运行产物。详见 [deployment_docker.md](./deployment_docker.md)。

## 知识库导入

```powershell
python -B scripts/import_knowledge_base.py .\docs --user-id default_user --name "项目文档知识库"
```

脚本会复制文件到 `storage/knowledge_bases`，调用统一文件处理器分块，并建立知识库 RAG 索引。
