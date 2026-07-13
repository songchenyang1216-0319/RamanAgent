# RamanAgent 生产化升级计划

## P0 已执行

- 建立 `docs/productization_gap_audit.md` 和本计划文档。
- 新增 `scripts/check_repo_secrets.py`，覆盖常见 API key、`.env.example`、跟踪的运行数据、数据库文件和大文件。
- CI 增加仓库安全扫描，并扩展 Linux/Windows 基础矩阵。
- 新增 `.pre-commit-config.yaml`，包含 secret scan、trailing whitespace、ruff 和大文件检测。
- 新增 `backend/security/startup_checks.py`，生产/预发环境强制校验 `AUTH_SECRET`、管理员密码、Graph Runtime 和非 mock RAG provider。
- 改造 `UserService`：新建 token 只保存 `token_hash`，支持 `revoked_at`、`last_used_at` 等字段，旧明文 token 只保留读取兼容。
- 扩展任务表字段，新增 `attempt`、`max_attempts`、`idempotency_key`、`cancel_requested`、`trace_id` 等字段。
- 新增 `backend/tasks/worker.py`，作为迁移期可运行 worker 入口。

## P0 剩余

- PostgreSQL 需要在真实 Docker 环境中跑完整集成测试。
- Redis/Celery 代码路径已接入，但当前本机环境没有安装/运行 Redis 服务，仍需容器验收。
- knowledge base、report、pipeline run、rag query、memory 仍需逐路由替换旧分散权限判断。
- RAG/报告/OCR 等长任务需要继续把 cancel checker 下沉到内部 batch 循环。

## P0 第二阶段已执行

- 新增 SQLAlchemy 2.x ORM 映射和 session factory。
- 新增 Alembic 环境与三段迁移：初始 schema、任务字段与 task_events、token hash 与 refresh_tokens。
- 新增 `scripts/migrate_legacy_storage.py`，支持 dry-run 和 JSON auth 存储迁移。
- 认证默认使用数据库主存储，旧 JSON 仅作为迁移/测试兼容。
- 增加 Refresh Token Rotation、replay 撤销 token family、logout-all、sessions 管理接口。
- 增加内存登录失败限流，Redis 分布式限流留作生产增强。
- 增加 `TaskQueueBackend`、`LocalTaskQueueBackend` 和可选 `CeleryTaskQueueBackend`。
- task events 持久化到 `task_events`，SSE 支持 `Last-Event-ID`、`after_sequence` 和 heartbeat。
- 新增 Ownership Guard，并接入 conversation、file、task 核心 API。
- production 启动检查 Alembic revision，不允许用 `init_database()` 替代迁移。

## P1 路线

- Graph Runtime 成为唯一生产入口，Legacy 保留兼容 adapter。
- ProviderCapabilities 接入所有 provider，优先原生 tool calling，fallback 到 JSON planner。
- RAG 2.0 增加 BM25、RRF、Cross-Encoder reranker、Evidence Verifier、Prompt Injection 检测和 golden eval。
- 长期记忆迁移到 `memories` 表，加入敏感度、过期、确认和用户管理 API。
- 上传 Skill 强化 ZIP 防护、权限确认和隔离 worker/container 执行。
- Observability 增加结构化 JSON 日志、OpenTelemetry、Prometheus metrics 和真实 ready checks。

## P2 路线

- 在不改成 React 的前提下拆分 `frontend/app.js` 为 ES Modules。
- 增加停止生成、重新生成、编辑重发、复制回答、删除消息、分支、断线重连、引用定位和移动端适配。
- Markdown 渲染接入 XSS 清洗、URL scheme 白名单和外链 `rel=noopener noreferrer`。

## 数据库迁移策略

- 短期继续使用当前 SQLite 兼容层，新增字段通过 `init_database()` 幂等添加。
- 中期引入 SQLAlchemy ORM，先映射现有表，再迁移 Repository。
- Alembic 首个 revision 需要以当前 `backend/db/models.py` 为基线，避免重建业务表。
- JSON 用户、token、memory 和 workspace 日志只允许迁移读取，不再作为生产主存储。

## 兼容验收

- 保留普通聊天、多模型切换、多会话、文件上传、RAG、Citation、Skill、Raman Pipeline、甲醇预测和报告生成。
- 旧路由如需调整必须加 deprecation header，不允许前端突然失效。
- Docker 默认仍能启动现有 SQLite 服务；PostgreSQL 服务存在但默认不强制启用，避免在 ORM 迁移完成前破坏启动。
