# 异步任务中心

## 目标

任务中心用于承接耗时操作，例如 Raman Pipeline、RAG 重建、报告导出、批量分析和 OCR。

当前入口：

- `backend/tasks/task_manager.py`
- `backend/tasks/task_queue.py`
- `backend/api/task_api.py`
- 前端 `任务中心`

## API

```text
POST /api/tasks
GET /api/tasks/{task_id}/events
POST /api/tasks/{task_id}/cancel
GET /api/tasks/{task_id}/artifacts
```

兼容接口：

- `POST /api/raman/pipeline/run?async_task=true`
- `POST /api/rag/rebuild-all?async_task=true`
- `POST /api/rag/rebuild-conversation-index?async_task=true`
- `POST /api/reports/export?async_task=true`
- `POST /api/methanol/batch-analyze?async_task=true`
- `POST /api/files/{file_id}/ocr?async_task=true`

## 状态

任务状态：

- `pending`
- `running`
- `succeeded`
- `failed`
- `cancelled`

任务事件：

- `task_created`
- `task_started`
- `tool_start`
- `tool_progress`
- `artifact_created`
- `task_succeeded`
- `task_failed`
- `task_cancelled`

## 当前实现

当前队列是本地 `ThreadPoolExecutor`，任务和事件写入 SQLite。这个设计方便以后替换 Celery/RQ：API 和 Repository 不需要变，替换 `LocalTaskQueue` 即可。
# 任务队列生产化说明

当前任务队列通过 `TaskQueueBackend` 统一接口接入：

- `LocalTaskQueueBackend`：pytest、离线开发、无 Redis 模式。
- `CeleryTaskQueueBackend`：生产 Redis/Celery 模式。

接口覆盖 `submit`、`cancel`、`retry`、`get_status`、`heartbeat`、`publish_event` 和 `recover_stale_tasks`。

任务事件写入 `task_events` 表，SSE 可以通过 `Last-Event-ID` 或 `after_sequence` 恢复。

## 启动

本地：

```powershell
$env:TASK_QUEUE_BACKEND="local"
python -m uvicorn backend.main:app
```

生产 worker：

```powershell
celery -A backend.tasks.celery_app.celery_app worker --loglevel=INFO --concurrency=1
```

迁移期轮询 worker 仍保留：

```powershell
python -m backend.tasks.worker
```

## 取消

`POST /api/tasks/{task_id}/cancel` 会设置 `cancel_requested=1`。Raman Pipeline 在每个 step 开始和 step 完成后检查取消信号。

## 重试与恢复

`POST /api/tasks/{task_id}/retry` 可重试 failed/dead_letter/cancelled 任务。worker 启动时会调用 stale recovery，处理 lease 过期任务。
