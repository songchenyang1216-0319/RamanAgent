from __future__ import annotations

from backend.security.sandbox_policy import SandboxPolicy


def assert_command_allowed(command: list[str] | str, policy: SandboxPolicy) -> None:
    if not policy.allow_subprocess:
        raise PermissionError("当前沙盒策略禁止执行子进程。")
    text = " ".join(command) if isinstance(command, list) else str(command)
    lowered = text.lower()
    for blocked in policy.blocked_commands:
        if blocked.lower() in lowered:
            raise PermissionError(f"沙盒禁止执行危险命令：{blocked}")
    if "invoke-webrequest" in lowered and ("http://" in lowered or "https://" in lowered):
        raise PermissionError("沙盒禁止通过 PowerShell 下载外部脚本。")
