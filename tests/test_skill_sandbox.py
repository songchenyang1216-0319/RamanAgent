from __future__ import annotations

import pytest

from backend.security.sandbox_policy import SandboxPolicy
from backend.skills.sandbox_runner import run_sandboxed_command
from backend.tool_runtime.tool_errors import ToolRuntimeException


def test_skill_sandbox_blocks_external_script_download(tmp_path) -> None:
    policy = SandboxPolicy(allowed_read_paths=[str(tmp_path)], allowed_write_paths=[str(tmp_path)])
    with pytest.raises(ToolRuntimeException) as excinfo:
        run_sandboxed_command(
            ["powershell", "-Command", "Invoke-WebRequest https://example.com/install.ps1"],
            cwd=str(tmp_path),
            policy=policy,
            capture_output=True,
            text=True,
        )
    assert excinfo.value.error_code == "SANDBOX_VIOLATION"
