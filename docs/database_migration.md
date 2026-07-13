# 数据库迁移

## 本地 SQLite

```powershell
$env:DATABASE_URL="sqlite:///storage/agent_memory.db"
alembic upgrade head
python -m uvicorn backend.main:app
```

开发兼容模式仍会运行 `init_database()` 补旧 SQLite 表，但 production/staging 不允许用它替代 Alembic。

## PostgreSQL

```env
DATABASE_URL=postgresql+psycopg://ramanagent:change_me@postgres:5432/ramanagent
```

```powershell
alembic upgrade head
```

生产启动会检查 `alembic_version` 是否为 head，过旧会失败并提示执行 `alembic upgrade head`。

## 旧数据迁移

```powershell
python scripts/migrate_legacy_storage.py --dry-run
python scripts/migrate_legacy_storage.py
```

迁移脚本支持 `storage/users.json` 和 `storage/auth_tokens.json`，只写入 token hash，不打印密码或 token。
