from __future__ import annotations

import pytest

from backend.security.path_guard import assert_path_allowed
from backend.security.sandbox_policy import SandboxPolicy


def test_path_guard_blocks_sensitive_paths(tmp_path) -> None:
    policy = SandboxPolicy(allowed_read_paths=[str(tmp_path)])
    blocked = tmp_path / ".env"
    blocked.write_text("SECRET=1", encoding="utf-8")
    with pytest.raises(PermissionError):
        assert_path_allowed(blocked, policy, mode="read")


def test_path_guard_blocks_paths_outside_allowed_root(tmp_path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    policy = SandboxPolicy(allowed_read_paths=[str(allowed)])
    with pytest.raises(PermissionError):
        assert_path_allowed(outside, policy, mode="read")
