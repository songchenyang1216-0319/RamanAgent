# RAG 评测

## 目标

RAG 现在记录检索片段、引用、回答、模型信息和延迟，并提供轻量评测框架。

核心文件：

- `backend/services/rag/rag_service.py`
- `backend/repositories/rag_query_repository.py`
- `backend/evaluation/rag_eval/*`

## 查询记录

RAG 回答会写入 `rag_queries`，字段包括：

- `query`
- `answer`
- `conversation_id`
- `retrieved_chunks_json`
- `citations_json`
- `latency_ms`
- `model_info_json`

## Citation 格式

引用包含：

- `source_type`
- `source_id`
- `file_id`
- `file_name`
- `page`
- `score`
- `content_excerpt`

## 运行评测

```powershell
python -m backend.evaluation.rag_eval.run --dataset .\docs\rag_eval_dataset.example.json
```

当前指标：

- retrieval hit rate
- citation accuracy
- answer groundedness
- faithfulness
- no-answer accuracy
- latency

评测框架是离线工具，不会在用户请求中自动调用。
