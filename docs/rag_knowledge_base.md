# RAG 与知识库说明

## 模式边界

RamanAgent 现在把检索增强拆成三种模式：

- `conversation_rag`：只检索当前会话上传或激活的文件。适合“根据这个文件回答”“刚才这些文件里有没有提到”等问题。
- `knowledge_base_rag`：只检索用户可访问、已启用的知识库。适合“查一下知识库里的规范”“根据资料库回答”等问题。
- `mixed_rag`：同时检索当前会话文件和知识库。适合“结合知识库和刚才文件分析”等问题。

普通知识问答，例如“RAG 是什么”“WebSocket 是什么”，仍走 `general_chat -> model`，不会因为出现 RAG 词汇就自动检索。

mixed RAG 可以通过下面配置开启轻量 rerank：

```env
RAG_ENABLE_RERANK=true
RAG_RERANK_PROVIDER=lexical
RAG_MIXED_MIN_PER_SOURCE=1
```

开启后会结合向量分和关键词重叠重新排序，并尽量保证结果里同时保留“当前会话文件”和“知识库”两类来源。

## 存储

- 会话文件仍进入当前 workspace 的 `uploads`，由 `WorkspaceManager.save_upload_file()` 注册到文件中心。
- 文件解析后的文本片段写入 SQLite 的 `file_chunks`。
- 知识库元数据写入 `knowledge_bases`。
- 知识库文件写入 `knowledge_base_files`。
- 知识库文本片段写入 `knowledge_base_chunks`。
- 向量索引状态写入 `rag_indexes`。
- 检索记录写入 `rag_queries`。
- 默认向量库目录由 `VECTOR_DB_DIR` 控制，默认 `storage/vector_db`。

## API

知识库：

- `GET /api/knowledge-bases`
- `POST /api/knowledge-bases`
- `GET /api/knowledge-bases/{knowledge_base_id}`
- `PATCH /api/knowledge-bases/{knowledge_base_id}`
- `DELETE /api/knowledge-bases/{knowledge_base_id}`
- `GET /api/knowledge-bases/{knowledge_base_id}/files`
- `POST /api/knowledge-bases/{knowledge_base_id}/files`
- `DELETE /api/knowledge-bases/{knowledge_base_id}/files/{kb_file_id}`
- `POST /api/knowledge-bases/{knowledge_base_id}/search`
- `POST /api/knowledge-bases/{knowledge_base_id}/reindex`
- `POST /api/knowledge-bases/{knowledge_base_id}/rebuild-index`
- `GET /api/knowledge-bases/{knowledge_base_id}/index-status`

会话绑定：

- `GET /api/conversations/{conversation_id}/knowledge-bases`
- `POST /api/conversations/{conversation_id}/knowledge-bases`
- `DELETE /api/conversations/{conversation_id}/knowledge-bases/{knowledge_base_id}`

RAG：

- `POST /api/rag/index-file`
- `POST /api/rag/rebuild-all`
- `POST /api/rag/rebuild-conversation-index`
- `POST /api/rag/query`
- `GET /api/rag/health`
- `GET /api/rag/status`

## 权限

- 生产环境继续使用 `get_request_user_context()` 校验用户。
- 文件检索前通过 `FileCatalogService.get_file_for_user()` 校验归属。
- 知识库读取、写入、管理分别通过 `KnowledgeBasePermissionService` 判断。
- `public` 知识库可读，但写入仍需要 owner/admin/editor 权限。

## 前端展示

- `/api/agent/chat` 返回 `route="rag"` 时，前端会展示 `rag_scope`、`retrieval_mode` 和 `citations`。
- 左侧“知识库”入口提供知识库 CRUD、上传文件、绑定/解绑当前会话、搜索、重建索引和索引状态查看。
- 右侧工作区展示当前会话 RAG、知识库 RAG 和向量库状态。
- 文件转换结果通过 artifact 卡片展示下载入口。
