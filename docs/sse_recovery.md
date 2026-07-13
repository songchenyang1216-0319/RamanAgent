# SSE 事件恢复

任务事件写入 `task_events` 表，每个任务的 `sequence` 单调递增。

## 读取事件

```http
GET /api/tasks/{task_id}/events
Last-Event-ID: <event_id>
```

也可以使用：

```http
GET /api/tasks/{task_id}/events?after_sequence=12
```

服务端会补发未读事件，并在空闲期间发送 `heartbeat`。任务完成、失败或取消后，事件流会在已持久化事件发送完毕后关闭。

## 事件类型

包括 `task_queued`、`task_started`、`tool_started`、`tool_progress`、`artifact_created`、`task_retrying`、`task_cancelled`、`task_failed`、`final`、`done` 和 `heartbeat`。

`final` 与 `done` 在 repository 层做去重，避免断线重连造成重复最终状态。
