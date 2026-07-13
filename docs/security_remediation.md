# 安全整改记录

## 本轮发现

- Git 跟踪列表中存在运行产物、用户记忆、原始数据和上传 Skill ZIP。
- `.env.example` 当前为占位值，未发现需要打印或复用的真实密钥。
- 历史提交中曾包含上述运行数据路径，单纯 `git rm --cached` 只能保护未来提交，不能清除历史。
- 旧 `auth_tokens.json` 设计保存明文 token；本轮已改为新 token 仅保存 hash，旧明文 token 只读兼容。

## 已执行的当前分支整改

- 更新 `.gitignore` 和 `.dockerignore`，忽略 `.env`、workspace、storage、outputs、数据库、jsonl、用户记忆、auth token、上传 Skill ZIP 和 `data/raw/`。
- 新增 `scripts/check_repo_secrets.py` 并接入 CI。
- 从 Git index 移除运行数据和用户数据，但不删除本机实际文件。

## 历史清理命令

在确认已备份并通知所有协作者后，可在维护窗口执行以下命令。不要在未协调的共享仓库上直接重写历史。

```powershell
python -m pip install git-filter-repo
git filter-repo `
  --path workspace `
  --path storage `
  --path outputs `
  --path data/raw `
  --path backend/data/skill_uploads `
  --path backend/data/uploaded_skills.json `
  --invert-paths
```

如果历史中发现真实密钥，先在对应平台轮换密钥，再执行历史清理和强制推送：

```powershell
git push --force-with-lease origin main
```

## 密钥轮换步骤

1. 在供应商控制台撤销旧 key。
2. 生成新 key 并写入部署平台 secret manager。
3. 更新 `.env` 或容器 secret，不提交到 Git。
4. 重启 API 和 worker。
5. 运行 `python scripts/check_repo_secrets.py --include-history` 验证当前分支和可读历史。

## 注意

- 本文不会记录任何旧密钥或疑似密钥原文。
- 历史清理会改变 commit hash，需要协作者重新拉取或重建本地分支。
