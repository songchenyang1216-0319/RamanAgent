# 测试说明

本文档用于帮助你快速验证 RamanAgent 的核心功能是否可用。

## 1. 启动前检查

在运行测试前，请先确认：

- `.env` 已经从 `.env.example` 复制并填写
- `artifacts/` 下的模型文件完整
- 后端可以正常启动
- 前端页面可以正常打开

## 2. 普通聊天测试

测试接口：`POST /api/agent/chat`

建议输入：

- `你好`
- `你是谁`
- `你能做什么`
- `谢谢`
- `你是不是只能回答拉曼问题`

期望结果：

- 返回自然、简洁的普通对话回复
- 不应报错
- 不应泄露 API Key

## 3. 上传 CSV 测试

测试接口：`POST /api/agent/analyze-file`

操作步骤：

1. 打开前端页面
2. 上传一个符合格式的 Raman 光谱 CSV
3. 观察页面是否显示上传中和分析中的状态
4. 查看返回的预测浓度、置信度、质量分析和建议

期望结果：

- 能返回分析结果
- 能显示 `session_id`
- 不会把本机绝对路径暴露到前端

## 4. 报告生成测试

测试接口：`POST /api/methanol/predict-report`

操作步骤：

1. 先完成一次 CSV 分析
2. 再点击报告生成或调用报告接口
3. 打开返回的 Markdown 或 HTML 报告链接

期望结果：

- 报告中包含预测结果、光谱质量分析、风险提醒和结论建议
- 报告中不包含 API Key
- 报告中不包含本机绝对路径

## 5. 模型信息接口测试

测试接口：

- `GET /api/models`
- `GET /api/models/current`

期望结果：

- 能看到默认模型版本
- 能看到模型列表
- 能看到缺失文件提醒
- 不暴露本机绝对路径

## 6. 历史记录测试

测试接口：`GET /api/history`

期望结果：

- 能查看最近的分析记录
- 能看到时间、文件名、预测浓度和置信度

## 7. 运行测试命令

完整测试：

```powershell
python -m pytest -q
```

如果只想快速检查核心功能，也可以分模块运行，例如：

```powershell
python -m pytest -q tests/test_agent_api.py tests/test_report_service.py
```

## 8. 常见失败原因

- `SILICONFLOW_API_KEY` 没有配置
- 模型文件缺失或路径不完整
- CSV 文件格式不符合要求
- 后端端口被占用
- 前端静态资源没有加载成功
