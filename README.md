# RamanAgent

RamanAgent 是一个面向 Raman 光谱分析的 Agent 系统，支持甲醇浓度预测、光谱预处理、专业分析、报告生成、历史记录查询和普通对话。

## 项目简介

这个项目主要用于处理上传的 Raman 光谱 CSV 文件，并给出面向甲醇分析场景的预测与解释结果。它既可以做专业分析，也可以像普通助手一样进行基础对话。

## 功能列表

- CSV 光谱上传
- 统一波数轴
- SG 平滑
- ALS 去基线
- CDAE 去噪
- CAE+ 基线估计
- SVR / RF 预测
- RamanAgent 对话
- 模型信息查询
- 历史记录
- 报告生成
- 光谱质量分析

## 项目结构

- `backend/`：后端 API、Agent 逻辑、模型服务、报告服务、工具函数
- `frontend/`：前端页面、样式和静态脚本
- `artifacts/`：模型文件、模型注册表、训练记录模板
- `outputs/`：运行产物，包括报告、图谱、上传文件和结果数据库
- `tests/`：自动化测试
- `docs/`：测试说明、部署补充说明等文档

## 环境准备

建议使用 Python 3.10 或 3.11。安装依赖前，先确保已经创建并激活虚拟环境。

在 Windows PowerShell 中可以这样做：

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

如果项目根目录使用的是其他依赖文件，请以仓库中的实际文件为准。

## 配置环境变量

先复制示例文件，再填写真实配置：

```powershell
Copy-Item .env.example .env
```

至少需要关注这些变量：

```env
SILICONFLOW_API_KEY=
SILICONFLOW_BASE_URL=
SILICONFLOW_MODEL=
```

说明：

- `SILICONFLOW_API_KEY`：你的真实 API Key，不要提交到仓库
- `SILICONFLOW_BASE_URL`：模型服务地址
- `SILICONFLOW_MODEL`：默认使用的模型名称

## Windows 本地启动

先启动后端，再打开前端页面。

### 启动后端

```powershell
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

如果你想直接用脚本，也可以执行：

```powershell
.\scripts\start_backend.ps1
```

### 打开前端

后端启动后，在浏览器访问：

```text
http://127.0.0.1:8000/app/index.html
```

如果你把前端单独部署到静态服务器，也可以通过对应的前端地址访问。

## 后端接口

常用接口包括：

- `POST /api/agent/chat`
- `POST /api/agent/analyze-file`
- `GET /api/models`
- `GET /api/models/current`
- `POST /api/methanol/predict-report`

## 运行测试

可以直接运行全量测试：

```powershell
python -m pytest -q
```

如果只想快速检查核心功能，也可以运行脚本：

```powershell
.\scripts\run_tests.ps1
```

详细测试说明见 [docs/testing.md](docs/testing.md)。

## 常见问题

### API Key 无效

检查 `.env` 中的 `SILICONFLOW_API_KEY` 是否填写正确，是否与当前环境匹配。

### 模型文件缺失

确认 `artifacts/` 下的模型目录和 `model_registry.json` 是否完整。若仍使用旧结构，请检查根目录旧模型文件是否保留。

### CSV 格式不对

确保上传的是有效的光谱 CSV 文件，且包含项目要求的波数和强度数据。

### 端口被占用

如果 `8000` 端口已被占用，可以改用其他端口，例如：

```powershell
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8001 --reload
```

### 前端访问不到后端

确认后端已启动，并且前端访问地址与后端端口一致。

## 安全提醒

- 不要提交 `.env`
- 不要提交 `outputs/` 下的运行产物
- 不要公开真实样品数据
- 不要把 API Key 写入代码、README 或测试

## Docker

当前仓库未新增 `Dockerfile` 和 `docker-compose.yml`。

原因是项目已经可以通过 Windows 本地 Python + Uvicorn 直接启动，继续保持轻量化更利于维护；如果后续需要容器化部署，可以再单独补充，不影响现有代码结构。
