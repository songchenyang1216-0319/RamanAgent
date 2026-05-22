# Test Prompts

## 1. Basic Skill discovery test

```text
测试上传Skill：请执行一次 Skill 握手自检。
```

Expected marker:

```text
SKILL_UPLOAD_TEST_OK_v1
```

## 2. English trigger test

```text
skill-handshake
```

Expected marker:

```text
SKILL_UPLOAD_TEST_OK_v1
```

## 3. Disable Skill test

First enable the Skill and ask:

```text
测试上传Skill
```

Then disable the Skill and ask again:

```text
测试上传Skill
```

When disabled, the Agent should not return the full Skill-defined diagnostic format.

## 4. Script execution test

Ask:

```text
使用上传Skill自检，并尝试运行 Skill 包里的 scripts/skill_test.py。
```

If script execution is supported, expected marker:

```text
SKILL_SCRIPT_EXEC_OK_v1
```
