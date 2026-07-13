# RamanAgent 产品化差距审计

本文记录本轮升级前的现状、可复用模块、主要风险和验收边界。目标是在保留现有 Raman、RAG、Skill、Graph Runtime 和前端兼容接口的前提下，把项目逐步推进到可安全部署的垂直 Agent 平台。

## 当前实现

- 后端入口已经是 FastAPI，核心路由覆盖聊天、文件、知识库、RAG、Skill、任务、审计、报告和 Raman Pipeline。
- 已存在 Graph Runtime、Legacy Orchestrator、Tool Runtime、PlanValidator、Repository 层和 SQLite 初始化脚本。
- RAG 已包含 mock/chroma/local embedding、Retriever、Reranker、Citation 和 mixed RAG。
- 任务中心已有 LocalTaskQueue、任务表、任务步骤事件和 SSE 接口。
- 认证已有 JSON 用户和 token 兼容层，但仍未完成数据库 token/refresh token 生产模型。
- Docker、CI、smoke check 和大量测试已经存在，但 CI 覆盖仍偏 demo 化。

## 可复用模块

- `backend/schemas/agent_response.py` 与 `backend/schemas/agent_stream.py` 可继续作为响应和流式事件契约。
- `backend/agent/runtime/*` 可作为正式 Graph Runtime 的收敛目标。
- `backend/tool_runtime/*` 已具备 schema 校验、权限、确认、超时和审计挂点。
- `backend/repositories/*` 与 `backend/db/models.py` 可作为迁移到 SQLAlchemy/Alembic 前的兼容层。
- `backend/services/rag/*` 可继续扩展 Hybrid Retrieval、Reranker、Evidence Verifier。
- `backend/security/skill_sandbox.py` 与 `backend/security/sandbox_policy.py` 是上传 Skill 安全强化的基础。

## 主要风险

- Git 当前曾跟踪 `outputs/`、`storage/users/.../memory.json`、`data/raw/` 和上传 Skill ZIP，需要从 index 移除并清理历史。
- `auth_tokens.json` 原设计保存明文 token，泄漏后风险较高；本轮已改为新 token 只保存 hash，旧 token 只读兼容。
- PostgreSQL、Alembic、Redis/Celery 仍不是完整生产实现，不能把当前系统宣称为已完成多节点生产部署。
- 生产环境如果继续使用 `admin/admin123`、缺少 `AUTH_SECRET` 或 mock RAG provider，会造成安全误配。
- SSE、Tool、RAG、Raman 的真实事件流还没有完全统一持久化，当前仍有局部兼容路径。

## 修改范围

- 新增仓库密钥与运行数据扫描。
- 加固 `.gitignore`、`.dockerignore`、CI 和 pre-commit。
- 增加生产启动安全校验。
- 增加 token hash 存储兼容。
- 扩展任务表字段、任务幂等键和最小 worker 入口。
- 从 Git index 移除已跟踪的运行数据和用户数据，不删除本机文件。

## 兼容方案

- 保留 `python -m uvicorn backend.main:app`。
- 保留 SQLite 默认开发路径，PostgreSQL 服务先在 Compose 中出现但不作为默认 `DATABASE_URL`。
- 保留旧 JSON 用户读取兼容，但新 token 不再保存明文。
- 保留 LocalTaskQueue；新增 worker 作为迁移期轮询 pending task 的入口。
- 开发匿名访问必须显式设置 `ALLOW_ANONYMOUS_DEV=true`。

## 验收标准

- `python scripts/check_repo_secrets.py` 对当前跟踪文件返回 0。
- `APP_ENV=production` 且缺少 `AUTH_SECRET` 或使用弱默认管理员密码时启动失败。
- `.env.example` 不包含真实密钥。
- Git index 不再跟踪 `storage/`、`outputs/`、`data/raw/` 和上传 Skill ZIP。
- 新 token 文件中不再写入完整 token 值。
- `POST /api/tasks` 支持 `idempotency_key`，重复键不会重复创建任务。
