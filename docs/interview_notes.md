# RamanAgent Interview Notes

## 1. 项目一句话介绍

RamanAgent 是一个面向 Raman 光谱分析场景的 Multi-Skill Agent 平台，支持普通对话、专业光谱分析、多文件 RAG、知识库问答、工具调用、模型切换和报告生成。

## 2. 项目解决的问题

- 普通 LLM 不擅长直接处理专业 Raman 光谱数据。
- 传统 Raman 脚本交互性差，难以沉淀为可复用工具链。
- 文档、实验数据和知识库分散，缺少统一问答和分析入口。
- Agent 调用工具需要安全边界、权限隔离和可观测执行轨迹。

## 3. 核心架构怎么讲

- Message Normalizer：统一整理 message、conversation、file、model、debug 等上下文。
- Intent Router：识别普通聊天、RAG、表格、Raman、Skill 等意图。
- Planner：把自然语言请求转换成结构化 Plan，决定走普通聊天、RAG、Raman Pipeline、表格工具、报告导出还是 Skill。
- PlanValidator：在执行前校验 tool/action 是否存在、required args 是否齐全、文件是否越权、高风险动作是否需要 confirmation。
- Tool Runtime：真正执行工具，统一处理 schema、权限、文件作用域、confirmation、timeout、retry、错误码和 audit log。
- RAG Service：负责分块、Embedding、索引、检索、rerank、citation 和 no-answer。
- Raman Pipeline：将 Raman 算法封装为可组合节点和模板流程。
- Response Builder/Frontend Renderer：展示最终回答、执行轨迹、引用和 artifacts。

## 3.1 为什么这是 Multi-Skill Agent

它不只是把用户问题转给 LLM。系统会根据意图选择不同能力：

- 普通聊天：走 LLM provider。
- 文档 RAG：走文件解析、分块、向量/关键词检索和 citation。
- mixed RAG：同时检索会话文件和绑定知识库。
- Raman Pipeline：调用专业算法节点生成图像、指标和报告摘要。
- Tool Runtime：执行文件、报告、任务、知识库等工具动作。
- Skill：通过 Skill registry 扩展新的动作集合。

所以它的核心价值是“规划和执行多种专业能力”，不是单轮文本生成。

## 4. 核心难点

- 如何防止 LLM 乱调用工具：Planner 只允许引用 ToolCatalog，PlanValidator 拦截不存在工具、缺参数、高风险未确认和越权文件。
- 如何保证 RAG 回答有依据：检索不到 chunk 时返回 no-answer；回答返回 citations，前端展示来源卡片。
- 如何做 mixed RAG：会话文件和绑定知识库分别检索，rerank 后保留 source_type 和 source_breakdown。
- 如何做工具权限和文件作用域隔离：ToolContext 携带 user/conversation/file_ids，ToolRuntime 在执行前校验。
- 如何封装 Raman Pipeline：每个算法节点有 algorithm_id、params、输入输出 shape、metrics、warning、error 和 artifacts。
- 如何让 CI 无 API Key 也能测试：mock embedding/vector/LLM planner 提供确定性测试链路，真实 Chroma/local embedding 单独手动开启。

## 4.1 RAG 如何防幻觉

- 检索不到足够相关 chunk 时返回 no-answer，不要求 LLM 编答案。
- 回答结果携带 citations，前端展示文件名、来源类型、页码/Sheet/section、score 和片段预览。
- RAG prompt 只注入检索片段，要求模型基于资料回答。
- mixed RAG 保留 `conversation_file` 与 `knowledge_base`，避免把临时文件和长期知识库混为一谈。
- mock embedding 只用于离线链路验证，不能宣传成真实语义检索；真实语义检索要跑 Chroma + local/remote embedding。

## 4.2 无 API Key 时为什么仍能测试

- CI 使用 mock LLM/embedding/vector provider 验证路由、权限、schema、RAG 数据结构、citation、Pipeline 和前端静态资源。
- Planner 有规则 fallback，关键 Raman/文件/RAG 场景不完全依赖外部 LLM。
- Raman Pipeline 的传统算法本地运行，不依赖 API Key。
- 真实 Chroma + local embedding 通过 `python -B scripts\verify_real_rag.py` 手动验收，不强制 CI 下载模型。

## 5. 面试问答

1. 你的 Agent 和普通聊天机器人有什么区别？
   它不是只生成文本，而是会根据意图规划工具调用，执行 RAG、表格分析、Raman Pipeline，并返回可验证 citation、图像和报告产物。

2. Planner 是怎么工作的？
   支持 off/mock/llm/hybrid。hybrid 模式优先高置信规则，其他请求调用 LLM Planner；失败时回到 deterministic mock 或旧路由。

3. RAG 是怎么实现的？
   文件处理器解析文件并写入 chunk 表，EmbeddingService 生成向量，VectorStore 写入 mock 或 Chroma，Retriever 检索，Reranker 重排，最后 LLM 基于上下文回答并返回 citation。

4. 为什么要有 keyword fallback？
   真实 embedding 或 vector store 不可用时仍能离线验证链路；也能补足短关键词、唯一编号等语义检索不稳定场景。

5. 为什么要有 rerank？
   初检可能混入弱相关 chunk，lexical rerank 能结合关键词重合度和向量分数排序，并在 mixed RAG 中保留来源平衡。

6. Chroma 存了什么？
   存 chunk embedding、chunk_id 和元数据，例如 user_id、conversation_id、file_id、knowledge_base_id、page、sheet、section、source_group。

7. 如何避免回答幻觉？
   没有足够检索结果时直接返回“资料中未找到足够依据”，不让 LLM 编造；有结果时也返回 citation 供用户核验。

8. Tool Runtime 做了什么？
   它统一执行工具，负责 action schema 校验、权限、文件作用域、confirmation、timeout、retry、错误码和 audit log。

9. Human Confirmation 有什么用？
   对删除、执行代码等高风险操作先返回 confirmation_required，用户确认后才执行，拒绝后不会执行。

10. 如何保证用户不能访问别人的文件？
    PlanValidator 和 ToolRuntime 都会检查 file_id 是否在当前用户、会话和 ToolContext 允许范围内。

11. Raman Pipeline 怎么设计？
    算法注册到 AlgorithmRegistry，PipelineRequest 由模板或自定义 steps 组成，Runner 顺序执行并记录每步 shape、metrics、artifact 和失败原因。

12. SG 和 ALS 分别是什么？
    SG 是 Savitzky-Golay 平滑，用局部多项式降低高频噪声；ALS 是非对称最小二乘基线估计，用于扣除荧光背景或基线漂移。

13. 为什么保留规则 fallback？
    高置信 Raman 固定任务、CI、无 API Key 和本地 mock 模式需要确定性行为，不能完全依赖外部模型。

14. Docker 和 CI 怎么做？
    Docker Compose 提供服务启动；GitHub Actions 安装依赖后执行环境安全检查、pytest 和 smoke_check。CI 默认 mock provider，不依赖外网模型。

15. 后续怎么扩展？
    可以接入真实 MCP server、补充深度学习 Raman 模型文件、升级数据库、增加真实 rerank 模型和更完整的前端截图/报告导出。
