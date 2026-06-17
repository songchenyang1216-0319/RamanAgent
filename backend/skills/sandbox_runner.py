from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from backend.security.command_guard import assert_command_allowed
from backend.security.path_guard import assert_path_allowed
from backend.security.sandbox_policy import SandboxPolicy
from backend.tool_runtime.tool_errors import ToolRuntimeException


def run_sandboxed_command(
    command: list[str],
    *,
    cwd: str | Path,
    policy: SandboxPolicy | None = None,
    **kwargs: Any,
) -> subprocess.CompletedProcess:
    sandbox_policy = policy or SandboxPolicy()
    try:
        assert_command_allowed(command, sandbox_policy)
        cwd_path = assert_path_allowed(cwd, sandbox_policy, mode="read")
        env = dict(os.environ)
        for key in list(env.keys()):
            upper = key.upper()
            if any(marker in upper for marker in sandbox_policy.blocked_env_keys):
                env.pop(key, None)
        process = subprocess.run(
            command,
            cwd=str(cwd_path),
            timeout=max(1, int(sandbox_policy.timeout_seconds)),
            env=env,
            **kwargs,
        )
        for attr in ("stdout", "stderr"):
            value = getattr(process, attr, "")
            if isinstance(value, bytes):
                value = value[: sandbox_policy.max_output_bytes]
            else:
                text = str(value or "")
                value = text[: sandbox_policy.max_output_bytes]
            setattr(process, attr, value)
        return process
    except ToolRuntimeException:
        raise
    except PermissionError as exc:
        raise ToolRuntimeException("SANDBOX_VIOLATION", str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise ToolRuntimeException("TOOL_TIMEOUT", "Skill 沙盒执行超时。") from exc
