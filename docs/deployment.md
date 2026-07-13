# 部署

## Docker Compose

```powershell
docker compose up --build
```

服务：

- `migration`：执行 `alembic upgrade head`
- `api`：FastAPI
- `worker`：Celery worker
- `postgres`：生产数据库
- `redis`：Celery broker/result backend/限流协调

## 必填生产环境变量

```env
APP_ENV=production
AUTH_SECRET=<32 chars minimum>
DEFAULT_ADMIN_PASSWORD=<strong password>
AGENT_RUNTIME_MODE=graph
DATABASE_URL=postgresql+psycopg://ramanagent:change_me@postgres:5432/ramanagent
TASK_QUEUE_BACKEND=celery
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1
REDIS_URL=redis://redis:6379/2
VECTOR_DB_PROVIDER=chroma
EMBEDDING_PROVIDER=local
ALLOW_ANONYMOUS_DEV=false
```

## 本地开发

```env
DATABASE_URL=sqlite:///storage/agent_memory.db
TASK_QUEUE_BACKEND=local
ALLOW_ANONYMOUS_DEV=true
```
