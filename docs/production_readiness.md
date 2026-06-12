# 生产部署与能力检查清单

## 必填安全项

- `.env` 不要提交，`.gitignore` 已忽略 `.env`、`.env.*`、`storage/`、`outputs/`。
- `.env.example` 只能放占位值，例如 `your_openai_api_key`，不要放真实 key。
- 生产环境设置 `APP_ENV=production` 后，接口默认要求显式登录 token。
- 不要开启过宽的 debug 输出；前端普通模式不会展示内部 debug。

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
- 前端 JS 语法检查

## 知识库导入

```powershell
python -B scripts/import_knowledge_base.py .\docs --user-id default_user --name "项目文档知识库"
```

脚本会复制文件到 `storage/knowledge_bases`，调用统一文件处理器分块，并建立知识库 RAG 索引。
