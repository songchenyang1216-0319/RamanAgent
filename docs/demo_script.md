# RamanAgent Demo Script

## Demo 0：启动与健康检查

输入/操作：

```powershell
python -B scripts\check_env_safety.py
python -B -m scripts.preflight_check
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

打开：`http://127.0.0.1:8000/app/index.html`。

预期输出：`GET /health` 返回 `{"status":"ok"}`，前端顶部显示后端已连接，左侧会话栏可加载。

失败时解释：如果后端启动失败，先看端口 8000 是否被占用；如果模型状态失败但 `/health` 正常，通常是 Raman 预测模型文件或外部 LLM Key 不完整，不影响 RAG、Pipeline 基础演示。

## Demo 1：普通聊天

输入：

```text
你好，请介绍一下你能做什么。
```

预期输出：返回普通助手回答，说明可处理文档、RAG、Raman 分析和报告产物。流式模式下会展示 Agent 执行轨迹，完成后轨迹自动折叠。

失败时解释：无 API Key 时外部大模型可能不可用，项目仍可通过 mock/规则链路验证路由、文件、RAG、Pipeline 和工具展示；不要把“无 Key 无法真实生成大模型答案”说成系统故障。

## Demo 2：文件上传状态

输入/操作：

1. 点击输入框旁的文件按钮。
2. 选择一个 `.md`、`.txt`、`.csv`、`.docx` 或 `.pdf` 文件。
3. 发送：`请总结这个文件的主要内容。`

预期输出：聊天区先显示用户消息和文件卡片；后端解析成功后，工作区文件列表能看到文件记录，RAG 可索引文本会写入 chunk 表。

失败时解释：扫描 PDF 或图片 OCR 需要 Tesseract/Poppler；普通文本型 PDF/DOCX/Markdown/TXT 不需要 OCR。上传失败时查看前端 toast、浏览器控制台和后端日志。

## Demo 3：会话文件 RAG

输入/操作：

1. 上传一份包含明确事实的文档，例如写有 `项目内部代号是 RA-2026-DEMO` 的 Markdown。
2. 等待上传成功。
3. 可手动调用索引接口，或让 Agent 在 RAG 请求中触发索引。
4. 输入：

```text
根据我刚才上传的文档，项目内部代号是什么？
```

预期输出：回答中应包含文档事实；回答下方展示 RAG 引用来源卡片，包含文件名、source_type、page/sheet/section、score 或“关键词匹配”、片段预览。

失败时解释：如果没有引用，说明没有检索到足够相关 chunk；可能原因是文件无可解析文本、未索引、问题和文本不匹配，或真实 embedding/Chroma 未正确加载。

## Demo 4：真实 Chroma + Local Embedding

输入/操作：

```powershell
python -B scripts\verify_real_rag.py
```

预期输出：终端打印 `Real Chroma + local embedding verification passed.`，并展示 `vector_provider=chroma`、`embedding_provider=local`、模型名、向量维度、retrieval_mode 和 top hit。

失败时解释：这是手动集成验收，不进 CI。脚本默认使用 `ramanagent_real_rag_verify` 独立 collection；业务 collection 如果曾写入不同维度向量，需要重建索引后才能切换 embedding 模型。其他常见失败原因是 `chromadb`/`sentence-transformers` 未安装、`BAAI/bge-small-zh-v1.5` 无法下载、网络代理问题或本地缓存损坏。失败时必须如实说明，不要声称已完成真实语义检索。

## Demo 5：知识库 RAG 与 mixed RAG

输入/操作：

1. 打开知识库面板。
2. 创建知识库，例如 `Raman 实验知识库`。
3. 上传知识库文件并重建索引。
4. 绑定该知识库到当前会话。
5. 再上传一份当前会话文件。
6. 输入：

```text
结合当前会话文件和知识库，说明甲醇 Raman 分析流程。
```

预期输出：回答的引用来源中同时出现 `conversation_file` 和 `knowledge_base`；source_breakdown 能区分会话文件和知识库来源，mixed RAG rerank 会尽量保留两类来源。

失败时解释：如果只出现一种来源，通常是另一类资料没有绑定、未索引、权限过滤未通过，或内容与问题不相关。

## Demo 6：Raman Pipeline

输入/操作：

1. 打开 Raman Pipeline 面板。
2. 上传 `data/demo/raman_demo_valid.csv`。
3. 选择 `basic_preprocessing` 模板。
4. 点击运行。

预期输出：结果区展示每一步状态、输入/输出点数、warning/error、图像 artifact 和报告摘要。SG 平滑、ALS 去基线、归一化等传统算法可运行。

失败时解释：CSV 必须包含可识别的 Raman 波数和强度列；`raman_demo_invalid.csv` 应该失败并展示明确失败步骤。CDAE/CAE+/Autoencoder 如果缺少真实模型文件，状态应为 unavailable，不能伪造深度学习结果。

## Demo 7：报告生成

输入/操作：

1. 完成一次 Raman Pipeline 或文件分析。
2. 在报告中心选择导出 Markdown/HTML。
3. 如配置了 PDF provider，再尝试 PDF 导出。

预期输出：报告中心出现报告记录，可下载 Markdown/HTML。默认 `PDF_EXPORT_PROVIDER=none` 时不会假装生成 PDF。

失败时解释：PDF 依赖 WeasyPrint/Playwright 等额外组件；OCR 依赖 Tesseract/Poppler。默认演示重点是 Markdown/HTML 和 Pipeline report 摘要。

## Demo 8：Agent 执行轨迹

输入：

```text
请分析这个 Raman CSV，并告诉我每一步做了什么。
```

预期输出：流式卡片展示 `识别意图 -> 生成计划 -> 校验计划 -> 执行工具 -> 生成结果`，工具调用卡片显示 tool/action、耗时、错误或 artifacts。完成后轨迹折叠，可手动展开。

失败时解释：如果流式接口失败，前端会回退普通聊天接口；普通响应仍应显示结果，但没有完整流式时间线。

## Demo 9：截图

保存位置：`docs/assets/demo/`。

推荐截图：

- `chat.png`
- `upload_status.png`
- `rag_citations.png`
- `mixed_rag.png`
- `agent_timeline.png`
- `raman_pipeline.png`

截图不是 CI 强依赖。若浏览器自动化不可用，可以按上述步骤手动截图，并在 README 中保留目录说明。
