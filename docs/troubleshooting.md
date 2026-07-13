# 故障排查

## production 启动失败

检查：

- `AUTH_SECRET` 是否设置且不是占位符。
- `DEFAULT_ADMIN_PASSWORD` 是否为强密码。
- `ALLOW_ANONYMOUS_DEV` 是否为 false。
- `AGENT_RUNTIME_MODE` 是否为 graph。
- 是否执行过 `alembic upgrade head`。

## ready 返回 503

查看：

- `/health/database`
- `/health/redis`
- `/health/worker`

生产环境下数据库 revision 不是 head、Redis 不可用或 Celery backend 配置错误都会导致 `/health/ready` 返回 503。

## Refresh Token 失效

Refresh Token Rotation 会撤销旧 token。旧 refresh token 再次使用会触发 replay 防护，并撤销同一 token family，需要重新登录。

## 任务无法恢复

检查 `tasks.lease_until`、`heartbeat_at`、`attempt` 和 `max_attempts`。worker 启动时会尝试恢复 lease 过期的任务，超过最大次数后进入 `dead_letter`。
