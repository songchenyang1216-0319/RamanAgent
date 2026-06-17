from __future__ import annotations

from pathlib import Path

from backend.security.sandbox_policy import SandboxPolicy


def _contains_blocked_marker(path: Path, policy: SandboxPolicy) -> bool:
    text = str(path).replace("\\", "/").lower()
    return any(marker.lower().replace("\\", "/") in text for marker in policy.blocked_paths)


def assert_path_allowed(path: str | Path, policy: SandboxPolicy, *, mode: str = "read") -> Path:
    resolved = Path(path).resolve()
    if _contains_blocked_marker(resolved, policy):
        raise PermissionError("沙盒禁止访问敏感路径。")
    allowed_roots = policy.allowed_write_paths if mode == "write" else policy.allowed_read_paths
    roots = [Path(item).resolve() for item in allowed_roots]
    if roots and not any(root == resolved or root in resolved.parents for root in roots):
        raise PermissionError("沙盒禁止访问授权目录之外的路径。")
    if resolved.exists() and resolved.is_file():
        size_mb = resolved.stat().st_size / (1024 * 1024)
        if size_mb > policy.max_file_size_mb:
            raise PermissionError(f"文件超过沙盒大小限制：{policy.max_file_size_mb}MB。")
    return resolved
