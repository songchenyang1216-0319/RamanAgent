# Demo 截图目录

本目录用于保存 RamanAgent 最终演示截图。推荐文件名：

- `chat.png`：普通聊天与模型状态。
- `upload_status.png`：文件上传、解析和索引状态。
- `rag_citations.png`：RAG 引用来源卡片。
- `mixed_rag.png`：会话文件与知识库 mixed RAG 来源区分。
- `agent_timeline.png`：Agent 执行轨迹，完成后可折叠。
- `raman_pipeline.png`：Raman Pipeline 步骤、图像产物和报告摘要。

生成方式：

1. 启动后端：`python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000`。
2. 打开：`http://127.0.0.1:8000/app/index.html`。
3. 按 `docs/demo_script.md` 逐步操作并截图。

如果本机安装了 Playwright 或其他浏览器自动化工具，也可以将自动截图保存到本目录。截图不是 CI 必需产物，避免让 CI 依赖浏览器或外网模型。
