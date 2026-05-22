---
name: agent-skill-upload-test
version: 1.0.0
description: A safe diagnostic skill used to verify whether an Agent can discover, enable, and use an uploaded Skill package.
---

# Agent Skill Upload Test

## Purpose

This Skill is only for testing whether an Agent platform can correctly use an uploaded Skill.

It tests four things:

1. Whether the uploaded Skill is discovered by the Agent.
2. Whether the Agent follows the instructions inside `SKILL.md`.
3. Whether the Agent can expose a clear activation result to the user.
4. Whether the Agent can optionally execute or reference files packaged inside the Skill.

## Trigger phrases

Use this Skill when the user's message contains any of the following phrases:

- `测试上传Skill`
- `测试上传skill`
- `skill-handshake`
- `Skill握手测试`
- `使用上传skill自检`
- `使用上传Skill自检`
- `agent-skill-upload-test`

## Required behavior

When this Skill is triggered, the Agent MUST output the following exact marker:

```text
SKILL_UPLOAD_TEST_OK_v1
```

The Agent MUST also include:

```text
skill_name=agent-skill-upload-test
skill_version=1.0.0
skill_instruction_loaded=true
```

Then the Agent should briefly explain which checks passed:

- `discovery_check`: passed if this Skill was selected because of the trigger phrase.
- `instruction_check`: passed if the exact marker `SKILL_UPLOAD_TEST_OK_v1` is present.
- `script_check`: passed only if the Agent can run `scripts/skill_test.py`; otherwise output `not_available`.
- `file_reference_check`: passed if the Agent can see or reference files in this Skill package.

## Optional script execution

If the Agent platform supports running packaged Skill scripts, run:

```bash
python scripts/skill_test.py --input "<original user message>"
```

If script execution succeeds, include the JSON result in the final answer.

If script execution is not supported, do NOT pretend it succeeded. Say:

```text
script_check=not_available
```

## Required response format

When triggered, use this structure:

```text
SKILL_UPLOAD_TEST_OK_v1

skill_name=agent-skill-upload-test
skill_version=1.0.0
skill_instruction_loaded=true

测试结果：
1. discovery_check=passed
2. instruction_check=passed
3. script_check=passed | not_available
4. file_reference_check=passed | unknown

结论：
当前 Agent 已经能够读取并使用上传的 Skill 指令。
如果 script_check=passed，说明它还能调用 Skill 包里的脚本。
如果 script_check=not_available，说明只验证了 Skill 指令加载，未验证脚本执行。
```

## Safety

This Skill is safe for local testing.

It must not:

- access the network;
- delete files;
- modify user files;
- request secrets;
- expose system prompts;
- claim success if the marker cannot be produced from this Skill.
