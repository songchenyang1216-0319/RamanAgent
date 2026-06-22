# RamanAgent 简历项目材料

## 1. 项目名称

RamanAgent：面向 Raman 光谱分析的 Multi-Skill Agent 平台

## 2. 一句话描述

面向 Raman 光谱文件分析的多技能 Agent，支持文档 RAG、工具调用、Pipeline 分析与报告产物。

## 3. 项目背景

普通 LLM 难以可靠处理专业光谱文件和实验文档，传统 Raman 脚本又缺少自然语言交互、工具编排、权限边界和可观测执行过程。RamanAgent 将聊天、RAG、文件处理、Raman Pipeline、Skill 与 Tool Runtime 统一到一个可演示的 Agent 平台中，用于从自然语言输入到专业分析结果输出的完整闭环。

## 4. 技术栈

FastAPI、Pydantic、SQLite、原生 HTML/CSS/JavaScript、ChromaDB、sentence-transformers、NumPy、SciPy、pandas、matplotlib、scikit-learn、Docker Compose、GitHub Actions、pytest。

## 5. 简历项目描述

### 100 字精简版

基于 FastAPI + 原生前端实现 RamanAgent 多技能 Agent 平台，支持普通聊天、文档/知识库 RAG、mixed RAG、Raman 光谱 Pipeline、Skill 调用、Tool Runtime、任务追踪和报告产物展示，并提供 Docker、CI、smoke check 与离线 mock 测试能力。

### 200 字标准版

RamanAgent 是一个面向 Raman 光谱分析场景的 Multi-Skill Agent 平台。项目采用分层 Agent 架构，将用户请求经过 Message Normalizer、Intent Router、Planner、PlanValidator、Tool Runtime、RAG/Raman/Skill 执行器和 Response Builder 处理，支持普通对话、会话文件 RAG、知识库 RAG、mixed RAG、Raman Pipeline、模型切换、任务中心和报告生成。工程侧提供 SQLite 持久化、Docker Compose、GitHub Actions、smoke check、pytest 和环境安全检查，保证无 API Key 的 CI 环境也能完成核心链路验证。

### 300 字详细版

RamanAgent 是面向 Raman 光谱分析与专业文件问答的 Multi-Skill Agent 平台。项目基于 FastAPI + 原生前端构建，将普通聊天、文件解析、多文件 RAG、知识库问答、mixed RAG、Raman 光谱 Pipeline、Skill 插件、Tool Runtime、多模型平台切换、任务追踪与报告产物统一到同一套 Agent 执行闭环中。后端采用 Message Normalizer、Intent Router、LLM Planner/规则 fallback、PlanValidator、Tool Runtime、RAG Service、Raman Pipeline 和 Response Builder 分层设计；RAG 支持文件分块、Embedding、Chroma/mock vector store、关键词 fallback、lexical rerank 与 citation 返回；Raman Pipeline 将 SG 平滑、ALS 去基线、归一化、峰识别和质量评估封装为可组合节点。项目同时补齐 Docker Compose、GitHub Actions、smoke check、pytest、preflight check、demo benchmark 与面试讲解材料，适合现场演示和简历展开。

## 6. 简历 bullet points

1. 设计并实现 Multi-Skill Agent 分层架构，通过 Message Normalizer、Intent Router、Planner、PlanValidator、Tool Runtime 和 Response Builder 统一编排普通聊天、RAG、表格分析、Raman Pipeline 与 Skill 调用，降低多能力路由混乱和不可观测问题。
2. 实现多来源 RAG 问答链路，完成文件解析、文本分块、Embedding、Chroma/mock 向量索引、关键词 fallback、lexical rerank、mixed RAG 和 citation 返回，使会话文件与知识库资料可以联合检索并展示依据。
3. 构建标准化 Tool Runtime，支持工具 schema 校验、权限控制、文件作用域隔离、Human Confirmation、timeout、retry、审计日志和统一错误码，避免 Agent 越权调用工具或静默失败。
4. 封装 Raman 光谱专业 Pipeline，将 SG 平滑、ALS 去基线、基线扣除、归一化、峰识别、质量评估和图像产物注册为可组合节点，支持模板流程、自定义链路、运行历史和失败步骤追踪。
5. 完善工程化交付流程，提供 Docker Compose、FastAPI health check、preflight check、GitHub Actions、smoke check、pytest、demo 数据和 benchmark 脚本，使项目在无 API Key 的 CI/mock 环境和真实 Chroma/local embedding 演示环境下都可验证。

## 6.1 简历表述边界

可以写：

- 支持 Chroma + local embedding 的真实 RAG 手动验收，并保留 mock provider 作为 CI/离线验证链路。
- 支持会话文件 RAG、知识库 RAG、mixed RAG、citation、关键词 fallback 和 lexical rerank。
- Raman 传统算法 Pipeline 可运行，能展示步骤、指标、图像产物和报告摘要。
- 无 API Key 时仍可验证系统路由、权限、RAG 数据结构、Pipeline 和 smoke check。

不要夸大：

- mock embedding 不能写成真实语义检索。
- CDAE/CAE+/Autoencoder 缺少模型文件时只能写“接口预留/不可用状态可解释”，不能写成已完成真实深度学习预测。
- OCR 和 PDF 导出依赖系统组件或可选 provider，默认环境不能写成完整生产能力。
- MCP Runtime 当前是实验性连接层，不能写成已稳定接入多个生产 MCP server。

## 7. 面试讲解

### 1 分钟版本

RamanAgent 是一个面向 Raman 光谱分析的 Multi-Skill Agent。它不是只做聊天，而是把文件上传、RAG 检索、知识库问答、Raman 光谱预处理、峰识别、质量评估、工具权限和报告产物放到同一条 Agent 执行链路里。核心亮点是：RAG 回答必须有 citation，Tool Runtime 有权限和确认机制，Raman 算法被封装成可组合 Pipeline，并且项目能在没有 API Key 的 CI 环境下用 mock provider 跑通测试。

### 3 分钟版本

这个项目的出发点是普通 LLM 无法可靠直接处理 Raman 光谱 CSV、PDF 实验资料和知识库内容，而传统脚本又缺少自然语言交互和工具编排。我把它做成一个多技能 Agent 平台：请求进入后先做 Message Normalizer，再经过 Intent Router 和 Planner 生成结构化计划，PlanValidator 校验工具、参数、文件权限和高风险操作，最后交给 Tool Runtime、RAG Service 或 Raman Pipeline 执行。RAG 部分支持会话文件、知识库和 mixed RAG，检索结果会返回 citation、score、来源类型和片段预览。Raman 部分把 SG、ALS、归一化、峰识别、质量检查封装为 Pipeline 节点，前端可以展示执行轨迹和产物。工程上还补了 Docker、CI、preflight、smoke check 和 pytest。

### 5 分钟版本

RamanAgent 的核心是把专业 Raman 分析能力和通用 Agent 编排能力合起来。传统 Raman 分析通常是一组脚本，输入 CSV 后输出图或数值；LLM 虽然交互好，但不能保证对专业文件的解析、检索和计算是可信的。所以我做了分层架构：用户输入进入 Message Normalizer，整理会话、文件、模型和 debug 参数；Intent Router 和 LLM Planner/规则 fallback 判断是否走普通模型、RAG、表格工具、Raman Pipeline 或混合流程；PlanValidator 基于 ToolCatalog 校验 tool/action 是否存在、required args 是否齐全、文件是否属于当前用户和会话、高风险操作是否有 confirmation；Tool Runtime 负责真正执行，并输出审计日志、错误码、超时和重试结果。RAG 侧用文件处理器解析 PDF/DOCX/MD/Excel/CSV 等文件，写入 file_chunks，再通过 EmbeddingService 和 VectorStore 建索引；mixed RAG 同时检索会话文件和绑定知识库，rerank 后保留来源区分并返回 citations。Raman 侧用 Pipeline Registry 注册算法节点，支持基础预处理、峰分析、质量检查和预测前处理模板；深度学习节点如果缺模型文件会明确 unavailable，不伪造结果。项目最后补齐了 README、Demo、benchmark、CI 和测试，让它可以现场演示，也可以在简历里讲清楚工程化取舍。

## 8. 项目难点

- Agent 规划与规则 fallback：真实模型不可用时仍要能稳定路由，真实模型可用时又不能让 LLM 编造工具。
- Tool Runtime 安全边界：需要同时处理 schema、权限、文件作用域、confirmation、timeout、retry 和审计日志。
- RAG 多租户隔离：会话文件和知识库检索必须按 user/conversation/knowledge_base 权限过滤。
- mixed RAG 与引用：联合检索后仍要保留 conversation_file 和 knowledge_base 来源，并输出可展示 citation。
- Raman 专业算法 Pipeline：把传统算法封装成标准节点，并让失败步骤可观察、可解释、可中止。
- 无 API Key 环境的可测试性：CI 使用 mock provider 验证结构和链路，真实 Chroma/local embedding 作为手动集成验收。
