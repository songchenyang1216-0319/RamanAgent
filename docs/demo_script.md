# Demo 演示脚本

## 1. 启动

```powershell
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

打开：

```text
http://127.0.0.1:8000/app/index.html
```

## 2. 普通聊天边界

发送：

```text
WebSocket 是什么？
```

预期：

- route 为 `model`
- 不调用 Raman Skill
- 不调用文件 Skill

## 3. 会话文件 RAG

上传一个 TXT/MD/PDF/DOCX 文件，发送：

```text
根据这个文件总结重点，并列出依据。
```

预期：

- route 为 `rag`
- rag_scope 为 `conversation`
- 回答下方显示引用片段

## 4. 知识库 RAG

打开左侧“知识库”：

1. 新建知识库。
2. 上传资料文件。
3. 绑定到当前会话。
4. 发送：

```text
查一下知识库里的项目规范。
```

预期：

- rag_scope 为 `knowledge_base`
- 知识库面板显示索引状态和 chunk 数

## 5. mixed RAG

在当前会话既有上传文件，也绑定知识库后发送：

```text
结合刚才文件和知识库，给我一份结论。
```

预期：

- rag_scope 为 `mixed`
- 引用来源同时包含“当前会话文件”和“知识库”
- 如果 `RAG_ENABLE_RERANK=true`，引用摘要里显示 rerank provider

## 6. OCR

上传图片或扫描 PDF，在工作区文件卡片点击 `OCR`。

预期：

- OCR 成功后新增文本 chunks
- 自动重建该文件 RAG 索引
- 失败时显示 OCR provider、语言包或 pdf2image/Poppler 依赖提示

## 7. 文件转换

上传 TXT/MD/DOCX/PDF，发送：

```text
把这个文件导出为 PDF。
```

预期：

- 如果未启用 PDF provider，生成 HTML fallback
- 响应中包含 `requested_format=pdf`、`actual_format=html`
- 前端展示下载卡片

## 8. Raman 专业分析

上传 Raman CSV，发送：

```text
分析这个 Raman 样品。
```

预期：

- 保留专业 Raman 分析链路
- 普通订单 CSV 不应误判为 Raman

## 9. Smoke Check

```powershell
.\scripts\smoke_check.ps1
```

预期输出包含：

```text
RAG smoke test passed.
backend.main ok
smoke_check passed
```
