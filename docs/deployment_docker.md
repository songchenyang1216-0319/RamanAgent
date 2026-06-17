# Docker 部署

## 构建

```powershell
.\scripts\docker_build.ps1
```

## 启动

```powershell
.\scripts\docker_up.ps1
```

访问：

```text
http://127.0.0.1:8000/app
```

## 开发模式

```powershell
.\scripts\docker_up.ps1 --dev
```

开发模式会挂载当前目录并启用 `uvicorn --reload`。

## 停止

```powershell
.\scripts\docker_down.ps1
```

或开发模式：

```powershell
.\scripts\docker_down.ps1 --dev
```

## 挂载目录

生产 compose 会挂载：

- `./storage:/app/storage`
- `./outputs:/app/outputs`
- `./artifacts:/app/artifacts`
- `./data:/app/data`

`data/raw` 不会打包进镜像，但运行时可通过挂载保留本地原始数据。
