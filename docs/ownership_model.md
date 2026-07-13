# Ownership Guard

统一权限入口：

- `backend/security/resource_scope.py`
- `backend/security/ownership_guard.py`

普通用户只能访问自己的 conversation、file、task 等资源。管理员跨用户访问会写入 audit log，记录资源类型、资源 ID、原因和 trace_id。

已接入的核心路由：

- `/api/conversations/*`
- `/api/files/{file_id}`
- `/api/files/{file_id}/download`
- `/api/files/{file_id}/preview`
- `/api/tasks/{task_id}/*`

后续应继续把 knowledge base、report、pipeline run、rag query 的旧分散判断迁移到同一 guard。
