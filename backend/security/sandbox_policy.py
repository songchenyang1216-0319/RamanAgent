from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from raman_core.methanol.config import OUTPUT_DIR, PROJECT_ROOT


@dataclass
class SandboxPolicy:
    allowed_workdir: str = str(PROJECT_ROOT)
    allowed_read_paths: list[str] = field(default_factory=lambda: [str(PROJECT_ROOT / "workspace"), str(PROJECT_ROOT / "outputs")])
    allowed_write_paths: list[str] = field(default_factory=lambda: [str(OUTPUT_DIR)])
    blocked_paths: list[str] = field(default_factory=lambda: [".env", "storage/users", "storage/auth_tokens"])
    blocked_env_keys: list[str] = field(default_factory=lambda: ["API_KEY", "SECRET", "TOKEN", "PASSWORD"])
    timeout_seconds: int = 60
    max_output_bytes: int = 1_000_000
    max_file_size_mb: int = 20
    allow_network: bool = False
    allow_subprocess: bool = True
    blocked_commands: list[str] = field(
        default_factory=lambda: [
            "rm -rf /",
            "del /s",
            "format",
            "shutdown",
            "curl | bash",
            "wget | bash",
            "Invoke-WebRequest",
        ]
    )

    @classmethod
    def for_uploaded_skill(cls, workspace_root: str | None = None, output_root: str | None = None) -> "SandboxPolicy":
        workspace = str(Path(workspace_root).resolve()) if workspace_root else str(PROJECT_ROOT / "workspace")
        output = str(Path(output_root).resolve()) if output_root else str(OUTPUT_DIR)
        return cls(
            allowed_workdir=workspace,
            allowed_read_paths=[workspace],
            allowed_write_paths=[output],
            timeout_seconds=60,
            allow_network=False,
        )
