# Security Policy

## 支持范围

当前安全维护重点覆盖 FastAPI 后端、认证、文件上传、RAG、Skill 上传、Raman Pipeline、任务中心、Docker 和 CI 配置。

## 漏洞报告

请通过私有渠道向项目维护者报告漏洞，内容包括：

- 影响范围；
- 复现步骤；
- 预期影响；
- 是否涉及用户上传文件、密钥、token 或数据库。

不要在公开 issue 中粘贴 API key、token、用户文档、数据库文件或完整日志。

## 密钥管理

- 不要提交 `.env` 或任何真实 API key。
- `.env.example` 只能包含占位符。
- 生产环境必须设置 `AUTH_SECRET`，长度至少 32 字符。
- 生产环境禁止使用默认管理员密码。
- 如果密钥泄漏，立即撤销旧密钥、生成新密钥、更新部署 secret 并重启服务。

## 数据泄漏处理

1. 立即冻结相关 token 或用户。
2. 轮换所有可能受影响的外部 API key。
3. 从 Git index 移除运行数据，必要时执行 `docs/security_remediation.md` 中的 `git filter-repo` 历史清理。
4. 审查审计日志、任务日志、RAG chunk、上传文件和 workspace。
5. 将事件、影响范围和修复动作记录到内部安全记录。

## 用户数据边界

- `workspace/`、`storage/`、`outputs/`、`data/raw/` 和上传 Skill 包视为用户或运行数据，默认不得提交。
- `auth_tokens.json`、`memory.json`、`messages.jsonl`、`errors.jsonl`、`task_steps.jsonl`、`skill_runs.jsonl` 不得提交。
- 新 token 只保存 hash；旧明文 token 仅为兼容读取，迁移后应清理。
- Refresh Token 使用 rotation；旧 refresh token 重放会撤销同一 token family。
- 生产环境不得启用 `ALLOW_ANONYMOUS_DEV`。

## 本地检查

```powershell
python scripts/check_repo_secrets.py
python scripts/check_repo_secrets.py --include-history
```
