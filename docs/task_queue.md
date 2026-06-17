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
