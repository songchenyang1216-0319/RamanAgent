# RamanAgent 架构收敛审计

生成时间：2026-06-22

本审计用于本轮“架构收敛、冗余清理和稳定性提升”的改动前基线。结论只基于当前仓库扫描与本地命令结果；未完成迁移的能力不会标记为已完成。

## 1. 当前后端主要调用链

- `backend/main.py` 创建 FastAPI 应用并挂载各业务 Router。
- 启动阶段当前仍调用 `init_database()`、`init_history_db()`、`init_agent_memory_db()`，因此存在多套数据库初始化入口。
- 主聊天入口仍是 `backend/agent/agent_router.py` 下的 `/api/agent/chat` 和 `/api/agent/chat/stream`。
- 新业务 Router 包括 `backend/api/model_api.py`、`backend/api/rag_api.py`、`backend/api/file_api.py`、`backend/api/task_api.py`、`backend/api/raman_pipeline_api.py`、`backend/api/skill_api.py`、`backend/api/report_api.py`、`backend/api/project_api.py`、`backend/api/auth_api.py` 等。
- Raman 模型注册入口是 `backend/model_registry/model_registry_router.py`，路径为 `/api/raman-models/*`。

## 2. 当前同步聊天调用链

当前 `/api/agent/chat` 调用链：

1. 前端 `frontend/js/api.js::sendAgentChat()` 调用 `POST /api/agent/chat`。
2. `backend/agent/agent_router.py::chat()` 根据 `Content-Type` 手动解析 JSON 或 FormData。
3. Router 内创建/解析 `conversation_id/session_id`，调用 `workspace_manager.create_workspace()`，写入用户消息到 Workspace JSONL，并调用旧 `session_store.append_message()`。
4. Router 处理上传文件、`file_ids`、active files、知识库 ID 和 `rag_scope`，组装 `orchestrator_payload`。
5. `AgentOrchestrator.handle_chat()` 按 `AGENT_RUNTIME_MODE=hybrid` 优先走 Graph Runtime，失败时 fallback 到 Legacy Runtime。
6. Router 根据响应创建任务 trace、写入 Skill trace、写入 assistant 消息、调用 `_finalize_workspace_response()`。
7. Router 更新 workspace task state 和 legacy session state 后返回最终 JSON。

风险：Router 同时承担 HTTP、请求解析、上下文构建、文件选择、任务 trace、持久化和兼容 session 写入，导致同步/流式逻辑重复。

## 3. 当前流式聊天调用链

当前 `/api/agent/chat/stream` 调用链：

1. 前端 `frontend/js/api.js::sendAgentChatStream()` 调用 `POST /api/agent/chat/stream`。
2. `backend/agent/agent_router.py::chat_stream()` 调用 `_prepare_chat_orchestrator_payload(request)`。
3. `_prepare_chat_orchestrator_payload()` 解析 JSON/FormData、创建 workspace/session、处理上传文件与 active files，并写入用户消息。
4. `AgentOrchestrator.handle_chat_stream()` 输出 start/status/planner/delta/final/done 等 SSE 事件。
5. final 事件到达时，`_persist_stream_chat_response()` 调用 `_finalize_workspace_response()`，将持久化后的响应替换到 final event 的 `response` 字段。

风险：流式入口已有较集中的 prepare/persist helper，但 helper 仍位于超大 Router 文件中，且同步入口未复用同一套解析流程。

## 4. Graph Runtime 与 Legacy Runtime 的关系

- `AgentOrchestrator.handle_chat()` 在 `AGENT_RUNTIME_MODE=legacy` 时直接调用 `_handle_chat_legacy()`。
- 在 `graph` 或 `hybrid` 模式下，优先构造 `GraphRunner(raise_on_error=True)` 并执行 Graph Runtime。
- Graph Runtime 抛出 `GraphFallbackRequested` 时，`hybrid` 模式 fallback 到 Legacy Runtime；`graph` 模式返回结构化 `graph_fallback_required` 错误。
- Graph Runtime 抛出其他异常时，`hybrid` 模式 fallback 到 Legacy Runtime；`graph` 模式返回 `graph_runtime_failed` 错误。
- 流式入口也遵循同一规则：Graph stream 失败时，`hybrid` 会输出状态事件并切到 Legacy stream。

结论：当前 Legacy Runtime 仍承担生产 fallback，不能直接删除。删除前必须建立 Graph/Legacy 一致性测试与 fallback 统计。

## 5. 当前所有数据库和实际文件路径

扫描发现的数据库入口与路径：

- `backend/db/session.py`：通过 `DATABASE_URL` 构造 SQLAlchemy engine；若未配置，则默认使用 `backend/db/database.py::DB_PATH`。
- `backend/db/database.py::DB_PATH`：当前指向 `outputs/results/ramanagent.db`。
- `.env.example` 与 Docker 配置中曾出现 `sqlite:///storage/agent_memory.db` 或容器路径 `sqlite:////app/storage/agent_memory.db`。
- 目标收敛方向应为唯一入口 `DATABASE_URL=sqlite:///storage/ramanagent.db`，但当前尚未完成。

实际文件状态源：

- `storage/workspaces/<user_id>/<conversation_id>/...`
- `storage/task_index.json`
- `outputs/results/ramanagent.db`
- `storage/vector_db`
- `outputs/uploads`
- `outputs/reports`
- `artifacts/`

## 6. 当前 conversations/messages 的所有存储位置

- 新表：`conversations`、`messages`，由 `backend/repositories/conversation_repository.py` 与 `backend/repositories/message_repository.py` 使用。
- 旧表：`agent_sessions`、`agent_messages`，由 `backend/agent/session_store.py` 使用。
- Workspace 审计/上下文：`storage/workspaces/<user>/<conversation>/logs/messages.jsonl`。
- Workspace 记忆快照：`storage/workspaces/<user>/<conversation>/context/memory_snapshot.json`。

结论：当前仍存在新旧表与 JSONL 多权威风险。后续应迁移旧表并将 JSONL 降级为可选审计副本。

## 7. 当前 tasks/task_steps/skill_runs 的所有存储位置

- 新表：`tasks`、`task_steps`、`skill_runs`，由 `TaskRepository`、`TaskManager` 和相关 Repository 使用。
- 旧兼容索引：`storage/task_index.json`。
- Workspace 状态：`storage/workspaces/<user>/<conversation>/context/task_state.json`。
- Workspace 日志：`storage/workspaces/<user>/<conversation>/logs/task_steps.jsonl`。
- Skill 日志：`storage/workspaces/<user>/<conversation>/logs/skill_runs.jsonl`。
- 内存事件：`LocalTaskQueue` / task event buffer。

结论：`TaskTraceManager` 当前仍承担兼容写入，后续应改造成委托 `TaskRepository` 的适配器。

## 8. 当前所有 LLM 模型 API

主入口：

- `GET /api/models/providers`
- `GET /api/models/providers/{provider_id}/models`
- `GET /api/models/current`
- `POST /api/models/select`
- `POST /api/models/refresh`

兼容/待废弃入口：

- `GET /api/llm/models`
- `GET /api/llm/models/current`
- `POST /api/llm/models/current`
- `GET /api/agent/models`
- `PATCH /api/agent/models/current`

结论：新代码应统一使用 `/api/models/*`。旧入口应保留兼容代理、增加 Deprecation/Sunset 标记和日志告警后再删除。

## 9. 当前所有 Raman 模型 API

Raman 模型注册入口：

- `GET /api/raman-models/current`
- `GET /api/raman-models`
- `GET /api/raman-models/{model_version}`
- `GET /api/raman-models/{model_version}/check`
- `POST /api/raman-models/current`
- `PATCH /api/raman-models/current`

Raman Pipeline 与训练/评测入口：

- `GET /api/raman/algorithms`
- `GET /api/raman/algorithms/{algorithm_id}`
- `GET /api/raman/pipeline/templates`
- `POST /api/raman/pipeline/validate`
- `POST /api/raman/pipeline/run`
- `GET /api/raman/pipeline/history`
- `GET /api/raman/datasets`
- `POST /api/raman/datasets`
- `POST /api/raman/benchmark/run`
- `GET /api/raman/benchmark/{benchmark_id}`
- `POST /api/raman/training/run`
- `GET /api/raman/models`
- `GET /api/raman/models/{model_id}`
- `POST /api/raman/models/{model_id}/activate`

结论：LLM 模型与 Raman 算法模型是两个概念，不能合并为同一套 API。

## 10. 前端实际使用的 API 列表

来自 `frontend/js/api.js` 与 `frontend/app.js` 扫描：

- 聊天：`POST /api/agent/chat`、`POST /api/agent/chat/stream`、`POST /api/agent/analyze-file`
- Legacy session：`POST /api/agent/session/new`、`GET /api/agent/session/{id}`、`POST /api/agent/session/{id}/clear`
- 文件：`GET /api/files`、`POST /api/files/upload`、`POST /api/files/convert`、`POST /api/files/{id}/ocr`、`GET /api/files/{id}`、`GET /api/files/{id}/download`、`DELETE /api/files/{id}`、`GET /api/files/{id}/preview`、`POST /api/files/{id}/activate`
- Workspace：`GET /api/workspaces/{conversation_id}/files`、`GET /api/workspaces/{conversation_id}/context`、`GET /api/workspaces/{conversation_id}/messages`
- RAG：`POST /api/rag/index-file`、`POST /api/rag/query`、`GET /api/rag/health`、`GET /api/rag/status`、`POST /api/rag/rebuild-all`、`POST /api/rag/rebuild-conversation-index`
- Knowledge Base：`/api/knowledge-bases/*` 与 `/api/conversations/{conversation_id}/knowledge-bases`
- LLM 模型：`/api/models/*`，并仍有 `/api/agent/models/current` fallback 调用
- Raman 模型：`/api/raman-models/*`
- Raman Pipeline：`/api/raman/algorithms`、`/api/raman/pipeline/*`、`/api/raman/models/*`
- 任务：`GET /api/tasks`、`POST /api/tasks`、`GET /api/tasks/{id}`、`GET /api/tasks/{id}/events`、`POST /api/tasks/{id}/cancel`、`GET /api/tasks/{id}/artifacts`
- Skill：`/api/skills/*`
- Auth：`/api/auth/register`、`/api/auth/login`、`/api/auth/logout`、`/api/auth/me`
- Projects：`/api/projects/*`
- Reports：`/api/reports/*`
- Tools/MCP/Audit：`/api/tools/*`、`/api/mcp/*`、`/api/audit-logs/*`

## 11. 冗余分类

### DELETE_NOW

- `backend/agent/agent_router.py::chat()` 中 `return finalized` 之后的旧分支代码。
  - 扫描结果：`return finalized` 位于 `backend/agent/agent_router.py:2310`；其后直到该函数结束前没有任何可达入口。
  - 前端引用：无，前端只调用 HTTP API。
  - 测试引用：无直接函数内分支引用。
  - 替代实现：`AgentOrchestrator.handle_chat()` 与 `chat()` 前半段已覆盖上传文件、Skill、RAG、任务与 workspace finalize。

### DEPRECATE

- `/api/agent/models`、`/api/agent/models/current`
  - 前端扫描：`frontend/js/api.js` 仍调用 `/api/agent/models/current` 作为模型切换兼容路径。
  - 处理策略：保留兼容代理，新增 Deprecation/Sunset header 和日志告警后再移除。
- `/api/llm/*`
  - 当前由 `backend/api/llm_api.py` 暴露。
  - 处理策略：迁移到 `/api/models/*` 后保留兼容代理。
- `/api/agent/session/*`
  - 前端仍使用 legacy session 管理。
  - 处理策略：迁移到 conversation API 后保留兼容代理。

### MIGRATE_THEN_DELETE

- `agent_sessions` / `agent_messages` 迁移到 `conversations` / `messages`。
- `users.json` / `auth_tokens.json` 迁移到数据库用户和 token 表。
- `storage/task_index.json`、workspace `task_state.json`、`task_steps.jsonl`、`skill_runs.jsonl` 的权威作用迁移到 `tasks`、`task_steps`、`skill_runs` 表。
- `messages.jsonl` 从核心业务数据源降级为可选审计副本。
- 运行时散落的 `ALTER TABLE` 迁移为正式 `backend/db/migrations/`。
- `init_database()`、`init_history_db()`、`init_agent_memory_db()` 收敛为 `backend/db/session.py` 与正式 migration 入口。

### KEEP

- Graph Runtime 与 `AGENT_RUNTIME_MODE=hybrid` fallback。
- Legacy Runtime fallback，直到 Graph/Legacy 一致性测试与 fallback 统计完成。
- Raman Pipeline 与 `raman_core`，核心预测入口仍为 `MethanolPredictor.predict`。
- ToolRuntime、Skill prompt_only/executable、Workspace、RAG、Knowledge Base、Chroma/local/mock provider。
- `/api/agent/chat` 与 `/api/agent/chat/stream` 路径和响应结构。
- `/api/models/*` 与 `/api/raman-models/*` 的职责分离。

## 12. 准备删除项引用扫描结果

本轮第一阶段仅准备删除不可达代码块，不删除文件。

删除项：`backend/agent/agent_router.py::chat()` 中 `return finalized` 后的旧逻辑。

扫描记录：

- `git grep -n "return finalized" backend/agent/agent_router.py`
  - `backend/agent/agent_router.py:2030`
  - `backend/agent/agent_router.py:2310`
- `git grep -n "/api/agent/chat" frontend tests docs README.md`
  - 前端、测试和文档均引用 HTTP API，不引用不可达分支。
- `git grep -n "sendAgentChat\\|chat/stream" frontend/js frontend/app.js`
  - 前端通过 `sendAgentChat()` 与 `sendAgentChatStream()` 调 HTTP API。

## 修改前基线命令

### python scripts/check_env_safety.py

结果：通过，退出码 0。

说明：脚本确认 `.env.example` 未发现真实密钥，`.env` 被忽略。

### python -m scripts.preflight_check

结果：通过，退出码 0；`errors=0, warnings=5`。

主要 warning：

- Sensenova 未配置真实 API key。
- 当前 embedding provider 为 mock。
- `VECTOR_DB_PROVIDER=chroma` 但当前系统 Python 环境缺少 `chromadb`。
- OCR 需要额外系统依赖。
- 检测到占位 key。

### python -m pytest -q

结果：通过，退出码 0。

说明：完整测试执行通过；测试输出含 FastAPI `on_event` deprecation、openpyxl/sklearn 等 warning。

### python -m compileall backend raman_core

结果：通过，退出码 0。

### docker compose -f docker-compose.dev.yml config

结果：通过，退出码 0。

安全备注：`docker compose config` 会展开本地 `.env` 中的敏感环境变量。后续 CI 和文档中不应记录完整输出，应改用占位 `.env.example` 或 secrets 注入。

## 第二阶段：Agent Router 拆分审计

### 修改前基线

- `git status --short`：仅包含上一阶段相关改动。
- `git diff --stat`：上一阶段主要改动为 `backend/agent/agent_router.py` 和 `tests/test_agent_streaming.py`。
- `git log -5 --oneline`：最近提交为 `16c56bd 优化逻辑`、`6c5c19f 演示可视化，前端流式回答增加时间线`、`343066f 多Agent,采用LangGraph框架`、`814b365 Improve streaming and skill robustness`、`15bb1a2 chore: ignore local workspace and venv artifacts`。
- `python -B scripts/check_env_safety.py`：通过。
- `python -B -m scripts.preflight_check`：通过，`errors=0, warnings=5`。
- `python -B -m pytest -q`：通过。
- `python -B -m compileall backend raman_core`：通过。

### agent_router.py 当前路由

第二阶段迁移后，`backend/agent/agent_router.py` 仅保留尚未拆分的 Agent 相关能力：

- `GET /api/agent/skills`
- `GET /api/agent/skills/logs`
- `POST /api/agent/skills/upload`
- `DELETE /api/agent/skills/{skill_name}`
- `PATCH /api/agent/skills/{skill_name}/enabled`
- `PATCH /api/agent/skills/{skill_name}/actions/{action_name}/enabled`
- `GET /api/agent/tools`
- `POST /api/agent/analyze-file`

已迁出：

- `POST /api/agent/chat` -> `backend/api/chat_api.py`
- `POST /api/agent/chat/stream` -> `backend/api/chat_api.py`
- `GET /api/agent/models` -> `backend/api/agent_compat_api.py`
- `PATCH /api/agent/models/current` -> `backend/api/agent_compat_api.py`
- `POST /api/agent/session/new` -> `backend/api/agent_compat_api.py`
- `GET /api/agent/session/{session_id}` -> `backend/api/agent_compat_api.py`
- `POST /api/agent/session/{session_id}/clear` -> `backend/api/agent_compat_api.py`

### 顶层函数和类分类

保留在 `agent_router.py` 的主要顶层对象：

- Skill/工具管理：`get_skills`、`get_skill_logs`、`upload_skill_zip`、`delete_skill`、`patch_skill_enabled`、`patch_action_enabled`、`get_tools`
- 文件分析兼容入口：`analyze_file`
- Raman/Skill 文件分析辅助：`_analyze_uploaded_file_with_skills`、`_analyze_csv_with_service_tools`、`_select_skill_route`、`_infer_table_skill_route`、`_build_skill_analysis_payload` 等
- 兼容会话摘要辅助：`_build_session_memory_response`，由 `agent_compat_api.py` 调用
- 兼容状态辅助：`_apply_task_state_from_response`、`_build_session_analysis_payload`，由 `chat_response_persistence.py` 和 `analyze-file` 继续使用

已移出的职责：

- 请求解析：`ChatRequestParser`
- 上下文构建：`ChatContextBuilder`
- 用户/助手消息与最终响应持久化：`ChatResponsePersistence`
- 聊天主路由：`backend/api/chat_api.py`
- Legacy model/session 兼容路由：`backend/api/agent_compat_api.py`
- Legacy API Deprecation header：`backend/api/deprecation.py`

### 聊天主链路

同步聊天现在为：

1. `ChatRequestParser.parse(request)`
2. `ChatContextBuilder.build(parsed)`
3. `ChatResponsePersistence.persist_user_turn(context)`
4. `orchestrator.handle_chat(context.to_orchestrator_payload())`
5. `ChatResponsePersistence.persist_final_response(context, response)`

流式聊天现在为：

1. `ChatRequestParser.parse(request)`
2. `ChatContextBuilder.build(parsed)`
3. `ChatResponsePersistence.persist_user_turn(context)`
4. `orchestrator.handle_chat_stream(context.to_orchestrator_payload())`
5. 仅在 `final` 事件中调用 `persist_final_response`

`ChatExecutionContext.persistence_state` 使用 `user_turn_persisted` 和 `final_response_persisted` 防止同一请求重复写入。客户端中途取消流式请求时，已经保存的用户消息不会重复写入；如果没有 final event，不会伪造助手成功消息。

### 只被同步/流式共同使用的函数

- `ChatRequestParser.parse`
- `ChatContextBuilder.build`
- `ChatExecutionContext.to_orchestrator_payload`
- `ChatResponsePersistence.persist_user_turn`
- `ChatResponsePersistence.persist_final_response`

同步和流式不再各自维护请求解析字典、文件选择逻辑和最终响应持久化逻辑。

### 兼容入口

明确兼容并已加 Deprecation header 的旧入口：

- `/api/agent/models` -> `/api/models/providers`
- `/api/agent/models/current` -> `/api/models/select`
- `/api/agent/session/*` -> `/api/conversations/*`
- `/api/llm/models` -> `/api/models/providers`
- `/api/llm/models/current` -> `/api/models/current` 或 `/api/models/select`

这些旧 API 本轮没有删除，返回体保持兼容；Deprecation 信息通过响应头和限频 warning 日志表达。

### 前端实际调用的 /api/agent/* 接口

前端仍调用：

- `/api/agent/chat`
- `/api/agent/chat/stream`
- `/api/agent/analyze-file`
- `/api/agent/models/current`
- `/api/agent/session/new`
- `/api/agent/session/{session_id}`
- `/api/agent/session/{session_id}/clear`
- `/api/agent/skills/upload`
- `/api/agent/skills/{skill_name}`
- `/api/agent/confirmations/*`

因此旧 Session、旧模型、Skill 管理和 confirmation 接口必须保留兼容。Skill 管理接口虽然存在 `backend/api/skill_api.py` 的新入口，但前端和测试仍调用 `/api/agent/skills/*`，本轮先保留在 `agent_router.py`，后续可单独迁移为兼容委托。

### tests 实际调用的 /api/agent/* 接口

测试仍覆盖：

- `/api/agent/chat`
- `/api/agent/chat/stream`
- `/api/agent/analyze-file`
- `/api/agent/tools`
- `/api/agent/skills/logs`

第二阶段新增测试覆盖：

- `tests/test_chat_request_parser.py`
- `tests/test_chat_context_builder.py`
- `tests/test_chat_response_persistence.py`
- `tests/test_chat_api.py`
- `tests/test_agent_compat_api.py`
- `tests/test_legacy_api_deprecation.py`

### 重复路由检查

`backend/main.py` 新增 `assert_no_duplicate_routes()`，按 `HTTP method + path` 检查重复注册。当前扫描结果：

- 重复路由数量：0
- `/api/agent/chat` 注册一次
- `/api/agent/chat/stream` 注册一次
- 旧 model/session 兼容接口注册一次

### 行数变化

- 上一阶段后 `backend/agent/agent_router.py` 约 2496 行。
- 第二阶段迁移后为 1761 行。

未降到 1200 行以内的原因：`agent_router.py` 仍保留 `analyze-file`、Skill 管理、Skill 上传删除、Raman/表格文件自动分流和旧文件分析辅助逻辑。下一阶段建议先拆 `analyze-file` 和 Skill 兼容路由，而不是为了行数机械搬运代码。

## 第三阶段：文件分析 API 与 Skill 兼容接口拆分

### 修改前基线

- `git status --short`：包含第二阶段未提交改动，未发现本轮外部新增业务变更。
- `python -B scripts\check_env_safety.py`：第二阶段基线通过。
- `python -B -m scripts.preflight_check`：第二阶段基线通过，`errors=0, warnings=5`。
- `python -B -m pytest -q`：第二阶段基线通过。
- `python -B -m compileall backend raman_core`：第二阶段基线通过。

### 本轮迁出的路由

从 `backend/agent/agent_router.py` 迁出：

- `POST /api/agent/analyze-file`
- `GET /api/agent/skills`
- `GET /api/agent/skills/logs`
- `POST /api/agent/skills/upload`
- `DELETE /api/agent/skills/{skill_name}`
- `PATCH /api/agent/skills/{skill_name}/enabled`
- `PATCH /api/agent/skills/{skill_name}/actions/{action_name}/enabled`

迁入的新模块：

- `backend/api/file_analysis_api.py`
  - `POST /api/files/analyze`：正式文件分析入口。
  - `POST /api/agent/analyze-file`：旧入口兼容代理，增加 `Deprecation`、`Sunset`、`Link` 响应头。
- `backend/services/file_analysis_service.py`
  - `FileAnalysisService`：集中处理上传文件分析、已注册文件分析、文件归属校验和旧分析 helper 调用。
  - 明确异常：`AgentFileNotFoundError`、`FilePermissionDeniedError`、`UnsupportedFileTypeError`、`AgentFileAnalysisError`。
- `backend/schemas/file_analysis.py`
  - `FileAnalysisRequest`、`FileAnalysisOptions`、`FileAnalysisResult`、`FileAnalysisError`。
- `backend/api/agent_skill_compat_api.py`
  - `/api/agent/skills/*` 旧路径兼容代理，统一委托 `SkillManagementService`，增加 Deprecation header。
- `backend/services/skill_service.py`
  - `SkillManagementService`：集中管理 Skill 列表、日志、上传、删除、启用、禁用。
- `backend/api/skill_api.py`
  - 正式 `/api/skills/*` 接口改为复用 `SkillManagementService`。
  - 新增正式 `POST /api/skills/upload` 与 `DELETE /api/skills/{skill_name}`。

### agent_router.py 当前状态

本阶段后 `backend/agent/agent_router.py` 仅注册：

- `GET /api/agent/tools`

保留在 `agent_router.py` 的旧分析 helper 仍被 `FileAnalysisService` 复用，原因是现有测试和历史行为仍依赖：

- `service.run_tool` monkeypatch 兼容测试。
- `_select_skill_route`、`_is_image_file_suffix`、`_is_table_file_suffix` 等路由判定函数。
- Raman CSV、普通表格、图片、prompt_only/executable Skill 的旧响应字段。

这些 helper 暂列为 `MIGRATE_THEN_DELETE`，后续可以迁到独立的 `backend/agent/file_analysis_router_compat.py` 或 `backend/services/file_analysis_legacy_adapter.py`，但本轮不做二次大搬迁。

### 前端调用扫描结果

前端仍调用以下旧路径：

- `frontend/js/api.js`：`/api/agent/analyze-file`
- `frontend/js/api.js`：`/api/agent/skills/upload`
- `frontend/js/api.js`：`/api/agent/skills/{skill_name}`

前端也已存在正式 Skill 路径调用：

- `frontend/js/api.js`：`/api/skills`
- `frontend/js/api.js`：`/api/skills/logs`
- `frontend/js/api.js`：`/api/skills/{skill_name}/enabled`
- `frontend/js/api.js`：`/api/skills/{skill_name}/actions/{action_name}/enabled`

结论：旧 `/api/agent/analyze-file`、`/api/agent/skills/upload`、`/api/agent/skills/{skill_name}` 仍需保留兼容代理，不能直接删除。

### 测试调用扫描结果

测试仍覆盖旧路径：

- `tests/test_agent_analyze_file_result.py`：`/api/agent/analyze-file`
- `tests/test_agent_session_context.py`：`/api/agent/analyze-file`
- `tests/test_agent_stage3.py`：`/api/agent/analyze-file`
- `tests/test_experiment_metadata.py`：`/api/agent/analyze-file`
- `tests/test_task_center_api.py`：`/api/agent/skills/logs`

本轮新增覆盖：

- `tests/test_file_analysis_api.py`
- `tests/test_skill_management_api.py`
- `tests/test_skill_upload_security.py`
- `tests/test_agent_router_stage3_refactor.py`

### 删除和保留分类

DELETE_NOW：

- `agent_router.py` 中 `/api/agent/analyze-file` 的路由函数体。
- `agent_router.py` 中 `/api/agent/skills/*` 的路由函数体。
- 由上述删除产生的 `File`、`Form`、`BaseModel`、`ToggleEnabledRequest`、`get_action`、`set_skill_enabled`、`set_action_enabled`、`delete_uploaded_skill`、`list_uploaded_skills`、`save_uploaded_skill` import。

DEPRECATE：

- `POST /api/agent/analyze-file`：兼容代理到 `/api/files/analyze`。
- `/api/agent/skills/*`：兼容代理到 `/api/skills/*`。

MIGRATE_THEN_DELETE：

- `agent_router.py` 中仍被 `FileAnalysisService` 调用的文件分析 helper。
- 前端 `frontend/js/api.js` 中仍调用旧路径的上传分析、Skill 上传和删除函数。

KEEP：

- `GET /api/agent/tools`：仍是 Agent 工具清单兼容入口。
- `RamanAgentService.run_tool` 兼容调用：旧 analyze-file 回归测试依赖 monkeypatch。
- `backend/skills/upload_service.py` 的 ZIP 安全校验：正式 Skill 上传服务继续复用。

### 路由重复检查

- `python -B -c "from backend.main import assert_no_duplicate_routes; assert_no_duplicate_routes(); print('routes ok')"`：通过。
- `agent_router.py` 注册路径扫描结果：仅 `@router.get("/tools")`。
- 应用路由扫描结果：
  - `POST /api/agent/analyze-file` 已注册。
  - `POST /api/files/analyze` 已注册。
  - `GET /api/agent/skills` 已注册。
  - `GET /api/skills` 已注册。

### 本轮定向验证

- `python -B -m compileall backend tests`：通过。
- `python -B -m pytest -q tests/test_file_analysis_api.py tests/test_skill_management_api.py tests/test_skill_upload_security.py tests/test_agent_router_stage3_refactor.py`：12 passed。
- `python -B -m pytest -q tests/test_agent_analyze_file_result.py tests/test_document_skill_routing.py tests/test_image_router_skill.py tests/test_prompt_only_skill_flow.py tests/test_uploaded_skill_runtime.py tests/test_legacy_api_deprecation.py tests/test_chat_api.py`：27 passed。

### 最终验收结果

- `python -B scripts\check_env_safety.py`：通过。
- `python -B -m scripts.preflight_check`：通过，`errors=0, warnings=5`。
- `python -B -m compileall backend raman_core`：通过。
- `docker compose -f docker-compose.dev.yml config`：通过。注意该命令会展开本地 `.env`，审计和总结不记录实际敏感值。
- `python -B -m pytest -q`：通过，当前收集测试数 274，结果 274 passed。

已知 warning：

- Pydantic V2 class-based `Config` deprecation。
- FastAPI `on_event` deprecation。
- openpyxl `datetime.utcnow()` deprecation。
- Tool confirmation 中 `datetime.utcnow()` deprecation。
- `test_predictor_smoke` 中 sklearn 模型 pickle 版本不一致 warning。
