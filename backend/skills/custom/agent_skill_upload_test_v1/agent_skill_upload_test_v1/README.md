# Agent Skill Upload Test v1

这是一个专门用来测试 Agent 是否能够使用“上传的 Skill”的最小测试包。

## 文件结构

```text
agent_skill_upload_test_v1/
├── SKILL.md
├── manifest.json
├── README.md
├── scripts/
│   └── skill_test.py
└── examples/
    ├── test_prompts.md
    └── expected_outputs.md
```

## 怎么用

1. 把 `agent_skill_upload_test_v1.zip` 上传到你的 Agent / Skill 管理页面。
2. 确认 Skill 已启用。
3. 在对话框输入：

```text
测试上传Skill：请执行一次 Skill 握手自检。
```

或者：

```text
skill-handshake
```

## 判断是否成功

### 情况 A：完全成功

如果 Agent 回复里包含：

```text
SKILL_UPLOAD_TEST_OK_v1
```

说明 Agent 至少成功读取并使用了 `SKILL.md` 中的指令。

如果还包含：

```text
SKILL_SCRIPT_EXEC_OK_v1
```

说明 Agent 不仅读取了 Skill 指令，还能执行 Skill 包里的脚本。

### 情况 B：只成功读取 Skill 指令

如果只有：

```text
SKILL_UPLOAD_TEST_OK_v1
```

但没有：

```text
SKILL_SCRIPT_EXEC_OK_v1
```

通常表示：

- Skill 上传成功；
- Skill 指令加载成功；
- 但当前 Agent 平台没有开放 Skill 脚本执行能力，或者你的后端还没有把脚本执行接上。

### 情况 C：失败

如果回复里完全没有：

```text
SKILL_UPLOAD_TEST_OK_v1
```

说明可能存在以下问题：

1. Skill 没有上传成功；
2. Skill 没有启用；
3. Agent 没有扫描 `SKILL.md`；
4. Skill 路由/匹配逻辑没有生效；
5. 前端切换模型或 Skill 后没有刷新；
6. Agent 后端没有把 Skill 内容注入到模型上下文。

## 禁用测试

你还可以测试“禁用 Skill”功能：

1. 先启用本 Skill；
2. 输入 `测试上传Skill`，确认能返回 `SKILL_UPLOAD_TEST_OK_v1`；
3. 禁用本 Skill；
4. 再输入 `测试上传Skill`。

禁用后，Agent 不应该再主动按照这个 Skill 的要求返回完整测试格式。

注意：如果你在问题里直接写出了 marker 字符串，普通模型可能会复述它。更可靠的测试方式是只输入触发词，不要直接输入 marker。
