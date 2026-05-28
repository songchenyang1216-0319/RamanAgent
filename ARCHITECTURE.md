# RamanAgent 架构说明

本文档说明当前 RamanAgent 项目已经落地的分层 Agent 架构，重点是把“用户输入 -> 统一编排 -> 技能/工具/模型执行 -> 统一响应 -> 前端展示”这条链路讲清楚，方便后续维护和扩展。

## 1. 架构目标

RamanAgent 不是单一聊天机器人，而是一个保留专业 Raman 分析能力的通用 Agent 平台。当前架构的核心目标是：

- 保留现有 Raman 光谱分析能力
- 保留普通聊天能力
- 保留 Skill 上传、Skill 管理、多模型切换
- 支持 prompt_only Skill 和 executable Skill
- 支持 CSV/Excel、文档、联网搜索的统一入口
- 所有后端返回统一成 `AgentResponse`
- 避免前端出现“有回答却显示发送失败”

## 2. 总体流程

```text
用户输入
  -> Message Normalizer
  -> Intent Router
  -> Planner
  -> Skill Router / Tool Runner / Model Router
  -> Response Builder
  -> Frontend Renderer
```

更具体一点：

```text
/api/agent/chat
  -> AgentOrchestrator.handle_chat()
  -> normalize(request)
  -> route_intent(normalized)
  -> make_plan(normalized, intent)
  -> execute(plan)
  -> build_response(...)
  -> 返回统一 AgentResponse
```

## 3. 核心分层

### 3.1 Message Normalizer

文件：

- [backend/agent/message_normalizer.py](./backend/agent/message_normalizer.py)

职责：

- 接收原始请求
- 统一整理 `message`、`files`、`conversation_id`、`selected_model`、`workspace_id` 等字段
- 识别文件类型：
  - `csv` / `xlsx` -> 表格
  - `txt` / `md` / `docx` / `pdf` -> 文档
  - Raman 数据 -> 光谱
  - `image` -> 图片
- 只做标准化，不直接回答问题

### 3.2 Intent Router

文件：

- [backend/agent/intent_router.py](./backend/agent/intent_router.py)

职责：

- 先用低成本规则识别明显意图
- 再预留 LLM 判断接口
- 支持的意图至少包括：
  - `general_chat`
  - `raman_analysis`
  - `document_processing`
  - `csv_analysis`
  - `web_search`
  - `skill_management`
  - `model_management`
  - `unknown`

### 3.3 Planner

文件：

- [backend/agent/planner.py](./backend/agent/planner.py)

职责：

- 根据 `IntentResult` 决定下一步怎么做
- 输出 `AgentPlan`
- 典型结果：
  - `route_type=skill`
  - `route_type=tool`
  - `route_type=model`
  - `route_type=hybrid`
  - `route_type=fallback`

### 3.4 Skill Router

文件：

- [backend/skills/skill_router.py](./backend/skills/skill_router.py)
- [backend/skills/skill_registry.py](./backend/skills/skill_registry.py)

职责：

- 识别 Skill 是 `prompt_only` 还是 `executable`
- 支持 Skill 上传与刷新
- 让 prompt_only Skill 只依赖 `SKILL.md` / `README.md` / `references/*` / `assets/*`
- 让 executable Skill 继续复用现有脚本执行能力

### 3.5 Tool Runner

文件：

- [backend/tools/tool_runner.py](./backend/tools/tool_runner.py)
- [backend/tools/csv_tool.py](./backend/tools/csv_tool.py)
- [backend/tools/document_tool.py](./backend/tools/document_tool.py)
- [backend/tools/web_search_tool.py](./backend/tools/web_search_tool.py)

职责：

- 处理适合直接工具化的任务
- CSV 工具负责基础信息、缺失值、统计预览
- 文档工具负责文档正文提取
- 联网搜索先保留接口位

### 3.6 Model Router

文件：

- [backend/llm/model_router.py](./backend/llm/model_router.py)
- [backend/llm/base_provider.py](./backend/llm/base_provider.py)
- 以及各 provider 文件

职责：

- 统一多模型调用入口
- 保留现有平台切换能力
- 不强制接 OpenAI API

### 3.7 Response Builder

文件：

- [backend/agent/response_builder.py](./backend/agent/response_builder.py)
- [backend/schemas/agent_response.py](./backend/schemas/agent_response.py)

职责：

- 把 Skill、Tool、Model、旧兼容返回统一成 `AgentResponse`
- 保证：
  - `success=true` 时，前端展示 `reply`
  - `success=false` 时，前端展示 `error_message`
  - 正常回答不会被塞进 `error_message`

### 3.8 Orchestrator

文件：

- [backend/agent/orchestrator.py](./backend/agent/orchestrator.py)

职责：

- 作为总入口接管 `/api/agent/chat`
- 串起标准化、意图识别、规划、执行、统一响应
- 所有分支都有 fallback
- 任意异常都会被捕获并转成统一响应

## 4. 统一响应格式

后端最终统一成 `AgentResponse`，结构如下：

```json
{
  "success": true,
  "reply": "...",
  "intent": "document_processing | raman_analysis | csv_analysis | general_chat | web_search | unknown",
  "route": "skill | tool | model | fallback",
  "skill_used": false,
  "skill_name": null,
  "skill_mode": null,
  "tool_used": false,
  "tool_name": null,
  "model_provider": "...",
  "model_name": "...",
  "artifacts": [],
  "debug": {},
  "error_message": null
}
```

规则很简单：

- `success=true` 时必须展示 `reply`
- `success=false` 时才展示 `error_message`
- `error_message` 只能放真正异常
- 不能出现“有结果但 success=false”

## 5. Skill 执行模式

### 5.1 prompt_only Skill

适用场景：

- 翻译
- 润色
- 文档总结
- 规则型提示词技能

特点：

- 有 `SKILL.md` 就算合法
- 不要求 `manifest.json`
- 不要求 `scripts/`
- 通过 Skill 文本上下文交给模型执行

### 5.2 executable Skill

适用场景：

- 需要脚本执行的专用技能
- 现有的文档处理、光谱处理、表格分析等脚本型逻辑

特点：

- 有 `manifest.json` 或 `scripts/` 即可
- 继续兼容现有执行逻辑
- 执行失败时返回真正的 `error_message`

## 6. 主要业务路由

### 6.1 普通聊天

```text
用户输入
  -> Message Normalizer
  -> Intent Router: general_chat
  -> Planner: route_type=model
  -> Model Router / 兼容旧聊天逻辑
  -> Response Builder
```

### 6.2 CSV / 表格分析

```text
用户输入 + CSV/Excel
  -> Message Normalizer
  -> Intent Router: csv_analysis
  -> Planner:
       - 精确查询 -> skill/data-analysis-skill
       - 泛化分析 -> tool/csv_tool
  -> TableQueryPlanner / DataAnalysisSkill 或 csv_tool
  -> Response Builder
```

### 6.3 文档处理

```text
用户输入 + 文档
  -> Intent Router: document_processing
  -> Planner:
       - prompt_only Skill -> prompt_only_runner
       - 文档抽取 -> document_tool
  -> Response Builder
```

### 6.4 Raman 分析

```text
用户输入 + Raman 文件
  -> Intent Router: raman_analysis
  -> Planner: hybrid
  -> 复用现有 Raman 专业链路
  -> Response Builder
```

### 6.5 联网搜索

当前已预留统一路由入口，后续可以继续接入真实搜索 provider，而不会改变外层 Agent 架构。

## 7. 前端展示规则

前端现在遵循统一响应结构：

- `success=true`：显示 `reply`
- `success=false`：显示 `error_message`
- 如果有 `skill_used` 或 `tool_used`，显示来源标签
- 不再把正常回答误判成“发送失败”

对应文件：

- [frontend/app.js](./frontend/app.js)
- [frontend/index.html](./frontend/index.html)
- [frontend/style.css](./frontend/style.css)

## 8. 关键代码入口

- `/api/agent/chat`
- `backend/agent/orchestrator.py`
- `backend/agent/planner.py`
- `backend/agent/intent_router.py`
- `backend/agent/message_normalizer.py`
- `backend/agent/response_builder.py`
- `backend/skills/skill_router.py`
- `backend/skills/prompt_only_runner.py`
- `backend/skills/executable_runner.py`
- `backend/tools/tool_runner.py`
- `backend/llm/model_router.py`

## 9. 当前实现状态

这套架构已经落地为“分层编排 + 兼容旧逻辑”的形态，当前重点是：

- 不删旧功能
- 不破坏 Raman 专业分析
- 不破坏普通聊天
- 不破坏 Skill 管理
- 不破坏多模型切换
- 统一响应格式

如果后续继续演进，建议优先做两件事：

1. 逐步收敛旧的分散路由，让更多请求都由 Orchestrator 统一接管
2. 把各类 Skill / Tool 的返回字段继续规范化，减少前端兼容分支
