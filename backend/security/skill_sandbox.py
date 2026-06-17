from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from raman_core.methanol.config import PROJECT_ROOT
from backend.security.sandbox_policy import SandboxPolicy
from backend.skills.sandbox_runner import run_sandboxed_command


BLOCKED_PATH_MARKERS = (
    ".env",
    "storage/users",
    "storage\\users",
    "storage/auth_tokens",
    "storage\\auth_tokens",
)


def validate_skill_path(path: str | Path, *, workspace_root: str | Path | None = None) -> Path:
    resolved = Path(path).resolve()
    root = Path(workspace_root or PROJECT_ROOT).resolve()
    text = str(resolved).replace("\\", "/").lower()
    if any(marker.lower().replace("\\", "/") in text for marker in BLOCKED_PATH_MARKERS):
        raise PermissionError("Skill 沙盒禁止访问敏感配置、用户或 token 存储。")
    if root != resolved and root not in resolved.parents:
        raise PermissionError("Skill 沙盒禁止访问当前工作区之外的路径。")
    return resolved


def run_skill_subprocess(
    command: list[str],
    *,
    cwd: str | Path,
    timeout: int,
    max_output_chars: int = 120_000,
    **kwargs: Any,
) -> subprocess.CompletedProcess:
    cwd_path = validate_skill_path(cwd)
    process = run_sandboxed_command(
        command,
        cwd=str(cwd_path),
        policy=SandboxPolicy(allowed_read_paths=[str(PROJECT_ROOT)], allowed_write_paths=[str(PROJECT_ROOT / "outputs")], timeout_seconds=max(1, min(int(timeout), 300))),
        **kwargs,
    )
    stdout = str(process.stdout or "")
    stderr = str(process.stderr or "")
    if len(stdout) > max_output_chars:
        process.stdout = stdout[:max_output_chars] + "\n[stdout truncated]"
    if len(stderr) > max_output_chars:
        process.stderr = stderr[:max_output_chars] + "\n[stderr truncated]"
    return process
