# RamanAgent MVP 第二阶段说明

## 新增功能说明

本阶段在不重写现有架构的前提下，把 RamanAgent 从“单次上传分析 Demo”推进为“可多人试用的 Raman 光谱分析工作台”。

已新增的核心能力：

1. 用户登录与权限系统
2. 项目中心
3. 报告中心与 Markdown / Word 导出
4. 批量 Raman CSV 分析
5. 数据隔离与受保护下载

## 用户系统说明

后端新增：

- `UserService`
- `POST /api/auth/register`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/auth/me`

用户字段：

- `user_id`
- `username`
- `password_hash`
- `role`
- `created_at`
- `last_login_at`
- `is_active`

说明：

- 密码不会明文保存，当前使用 `pbkdf2_hmac("sha256")`
- 登录后返回 bearer token
- 前端会把 token 存在浏览器本地，并自动附加到后续 API 请求
- `APP_ENV=development` 下允许创建默认 admin，方便本地开发

## 项目管理说明

后端新增 `ProjectService`，当前使用 JSON 存储，可后续迁移到 SQLite / PostgreSQL / MySQL。

项目字段：

- `project_id`
- `user_id`
- `name`
- `description`
- `created_at`
- `updated_at`
- `archived`
- `file_count`
- `task_count`
- `report_count`

已支持：

1. 创建项目
2. 查看项目列表
3. 选择当前项目
4. 上传文件时直接绑定项目
5. 将已有文件绑定到项目
6. 查看项目下文件、任务、报告
7. 软删除归档项目

## 报告导出说明

后端新增：

- `ReportRegistryService`
- `ReportExportService`

报告记录字段：

- `report_id`
- `user_id`
- `project_id`
- `task_id`
- `file_id`
- `title`
- `report_type`
- `created_at`
- `markdown_path`
- `html_path`
- `pdf_path`
- `docx_path`
- `json_path`
- `status`
- `error_message`

当前支持：

1. Markdown 导出
2. HTML 展示文件索引
3. Word `.docx` 基础导出
4. JSON 导出

当前限制：

- PDF 仍然是“可选能力”
- 当前环境默认不强依赖中文 PDF 渲染库，因此接口会返回 warning，而不是伪造一个不可用 PDF

## 批量分析说明

后端新增 `BatchAnalysisService`，接口如下：

- `POST /api/methanol/batch-analyze`
- `GET /api/methanol/batch-tasks/{task_id}/summary`
- `GET /api/methanol/batch-tasks/{task_id}/download-csv`

行为说明：

1. 批量任务会创建一个父任务
2. 每个文件会创建一个子任务
3. 单文件失败不会中断整个批量任务
4. 汇总结果会输出 JSON 和 CSV
5. 结果里包含成功数、失败数、每文件状态、质量评分、峰位和错误原因

## 本地启动方式

1. 安装依赖

```bash
pip install -r requirements.txt
```

2. 启动后端

```bash
uvicorn backend.main:app --reload
```

3. 浏览器打开

```text
http://127.0.0.1:8000/app/
```

## 测试账号创建方式

方式 1：前端页面直接注册

方式 2：调用接口注册

```http
POST /api/auth/register
{
  "username": "demo",
  "password": "123456"
}
```

## 手动测试步骤

1. 打开前端页面并注册账号
2. 登录后确认顶部显示当前用户名
3. 创建一个项目
4. 在文件中心上传 Raman CSV，并确认文件已绑定当前项目
5. 点击“分析”验证单文件分析链路
6. 点击“导出 MD / 导出 Word”验证报告导出
7. 勾选多个 CSV，点击“批量分析选中文件”
8. 到任务中心查看批量任务状态
9. 下载批量分析 CSV
10. 用第二个普通用户登录，确认无法访问第一个用户的文件与报告

## 已知限制

1. PDF 目前未默认启用真实中文渲染
2. 当前 token 方案是轻量 bearer token，适合 MVP，后续可升级为 JWT
3. 项目 / 文件 / 报告 / 任务当前使用 JSON 索引，适合 MVP，不适合高并发
4. 批量分析当前是同步请求式体验，后续可升级为真正异步队列

## 下一阶段 TODO

1. 报告 PDF 导出接入可稳定支持中文的渲染链路
2. 批量分析任务做成异步队列与进度推送
3. 增加会话列表和会话归档
4. 把用户、项目、任务、报告迁移到数据库
5. 增加管理员后台与用户管理
6. 补充分页、筛选、排序、按项目聚合统计
