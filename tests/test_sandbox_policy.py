from __future__ import annotations

from backend.security.sandbox_policy import SandboxPolicy


def test_uploaded_skill_sandbox_policy_is_restricted(tmp_path) -> None:
    policy = SandboxPolicy.for_uploaded_skill(workspace_root=str(tmp_path / "workspace"), output_root=str(tmp_path / "outputs"))
    assert policy.allow_network is False
    assert policy.timeout_seconds <= 60
    assert len(policy.allowed_read_paths) == 1
    assert len(policy.allowed_write_paths) == 1
    assert any(".env" in item for item in policy.blocked_paths)
