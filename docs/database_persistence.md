# 统一持久化层

## 目标

RamanAgent 现在新增统一 SQLite 持久化层，用来承接后续从 JSON 文件逐步迁移到数据库的工作。

当前入口：

- `backend/db/session.py`：数据库连接和 `session_scope`
- `backend/db/models.py`：表结构定义
- `backend/db/init_db.py`：启动时建表和增量补列
- `backend/repositories/*`：Repository 封装

## 默认配置

```env
DATABASE_URL=sqlite:///storage/agent_memory.db
```

未配置时会继续使用 `backend/db/database.py` 中的默认 `DB_PATH`。Windows 盘符路径和 Linux 容器路径都已兼容。

## 当前表

统一表覆盖：

- `users`
- `projects`
- `files`
- `conversations`
- `messages`
- `tasks`
- `task_steps`
- `reports`
- `pipeline_runs`
- `rag_queries`
- `skill_runs`
- `model_runs`
- `knowledge_bases`
- `knowledge_base_files`
- `audit_logs`

## 迁移原则

- 新功能优先使用 Repository。
- 旧 JSON 存储先作为兼容层保留。
- `init_database()` 只做 additive schema 更新，不删除旧数据。
- 不把 API key、原始数据或用户上传内容写入代码。

## 后续扩展

`DATABASE_URL` 已预留 PostgreSQL 形态。当前运行时仍只内置 SQLite，如要迁移 PostgreSQL，需要在 `backend/db/session.py` 增加对应 adapter。
