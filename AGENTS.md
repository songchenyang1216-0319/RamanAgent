# RamanAgent 开发说明

## 项目目标

RamanAgent 甲醇拉曼光谱预测模块，面向后续 FastAPI、Agent 调度、MCP 工具接入和报告生成。

## 当前主流程

CSV -> 预处理 -> CDAE -> CAE+ -> SVR/RF -> 结果输出

## 重要规则

- 不要删除 `artifacts/`
- 不要覆盖 `data/raw/` 原始数据
- 不要把 API key 写死到代码中
- 不要让 UI 直接包含算法逻辑
- 核心预测入口是 `MethanolPredictor.predict`

## 常用命令

- `python -m py_compile raman_core\methanol\*.py`
- `python apps/ui_v3.py`
- `python -m scripts.train_v3`

## 后续扩展方向

- FastAPI
- MCP
- 报告生成
- 大模型解释
