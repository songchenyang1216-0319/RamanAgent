# Skill 沙箱

## 目标

上传 Skill 的可执行脚本需要更严格的路径和环境控制，避免读取敏感文件或继承 API key。

核心文件：

- `backend/security/sandbox_policy.py`
- `backend/security/path_guard.py`
- `backend/security/command_guard.py`
- `backend/security/skill_sandbox.py`
- `backend/skills/sandbox_runner.py`
- `backend/skills/uploaded_package_skill.py`

## 路径限制

Skill 输入路径必须位于项目根目录或指定 workspace 内，且禁止访问：

- `.env`
- `storage/users`
- `storage/auth_tokens`

`SandboxPolicy.for_uploaded_skill()` 默认只允许读取 workspace，只允许写入 outputs。

## 命令限制

`command_guard` 会阻止明显危险命令：

- `rm -rf /`
- `del /s`
- `format`
- `shutdown`
- `curl | bash`
- `wget | bash`
- `Invoke-WebRequest`

同时会阻止通过 PowerShell 从外部 URL 下载脚本。

## 环境变量

执行 Skill 子进程前会剥离包含以下片段的环境变量：

- `API_KEY`
- `SECRET`
- `TOKEN`
- `PASSWORD`

## 超时

Skill 子进程最大超时限制为 300 秒，stdout/stderr 会截断保存，避免异常输出撑爆响应。

## 错误码

- 路径或命令被阻止：`SANDBOX_VIOLATION`
- 执行超时：`TOOL_TIMEOUT`

## 测试

```powershell
python -m pytest tests/test_sandbox_policy.py
python -m pytest tests/test_path_guard.py
python -m pytest tests/test_skill_sandbox.py
```
