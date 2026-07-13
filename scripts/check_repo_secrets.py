from __future__ import annotations

import argparse
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MAX_FILE_MB = 10
MAX_TEXT_SCAN_BYTES = 2 * 1024 * 1024

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai_or_compatible_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b")),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{30,}\b")),
    ("aws_access_key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("huggingface_token", re.compile(r"\bhf_[A-Za-z0-9]{30,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |DSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("authorization_bearer", re.compile(r"(?i)\bauthorization\s*[:=]\s*bearer\s+[A-Za-z0-9._~+/=-]{20,}")),
)

CONFIG_SECRET_ASSIGNMENT = re.compile(
    r"(?im)^[^\S\r\n]*([A-Z][A-Z0-9_]*(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|AUTHORIZATION|PRIVATE[_-]?KEY)[A-Z0-9_]*)[^\S\r\n]*[:=][^\S\r\n]*['\"]?([^'\"\s#\r\n]{8,})"
)

CONFIG_SUFFIXES = {
    ".env",
    ".example",
    ".ini",
    ".json",
    ".md",
    ".toml",
    ".yaml",
    ".yml",
}

FORBIDDEN_PREFIXES = (
    "workspace/",
    "storage/",
    "outputs/",
    "output/",
    "data/raw/",
    "backend/data/skill_uploads/",
)

FORBIDDEN_EXACT_NAMES = {
    ".env",
    "auth_tokens.json",
    "messages.jsonl",
    "errors.jsonl",
    "task_steps.jsonl",
    "skill_runs.jsonl",
    "memory.json",
}

FORBIDDEN_EXACT_PATHS = {
    "backend/data/uploaded_skills.json",
}

FORBIDDEN_SUFFIXES = (
    ".db",
    ".db-shm",
    ".db-wal",
    ".sqlite",
    ".sqlite3",
)

LARGE_FILE_ALLOW_PREFIXES = (
    "artifacts/",
    "docs/assets/demo/",
    "data/demo/",
)

HISTORY_GREP_PATTERN = (
    r"sk-(proj-)?[A-Za-z0-9_-]{20,}|sk-ant-[A-Za-z0-9_-]{20,}|"
    r"gh[pousr]_[A-Za-z0-9_]{30,}|(AKIA|ASIA)[0-9A-Z]{16}|"
    r"AIza[0-9A-Za-z_-]{35}|hf_[A-Za-z0-9]{30,}|"
    r"xox[baprs]-[A-Za-z0-9-]{20,}|"
    r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
)


@dataclass(frozen=True)
class Issue:
    code: str
    message: str


def _run_git(args: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _git_paths(args: list[str]) -> list[str]:
    result = _run_git(args)
    if result.returncode != 0:
        return []
    return [item for item in result.stdout.decode("utf-8", errors="replace").split("\0") if item]


def _normalize_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def _line_number(text: str, position: int) -> int:
    return text.count("\n", 0, position) + 1


def _is_placeholder(value: str) -> bool:
    cleaned = value.strip().strip("'\"").lower()
    if cleaned in {"", "none", "null", "false", "0"}:
        return True
    placeholder_prefixes = (
        "${",
        "your_",
        "your-",
        "ci_",
        "example",
        "placeholder",
        "changeme",
        "change_me",
        "replace_me",
        "dummy",
        "mock",
        "test_",
        "unit_",
        "phase2_",
        "dev_",
    )
    return cleaned.startswith(placeholder_prefixes) or set(cleaned) <= {"x", "_", "-"}


def _is_config_file(rel_path: str) -> bool:
    name = Path(rel_path).name.lower()
    suffix = Path(rel_path).suffix.lower()
    return name.startswith(".env") or suffix in CONFIG_SUFFIXES


def _is_binary_sample(data: bytes) -> bool:
    return b"\0" in data


def _read_text_for_scan(path: Path) -> str | None:
    try:
        with path.open("rb") as handle:
            data = handle.read(MAX_TEXT_SCAN_BYTES + 1)
    except OSError:
        return None
    if _is_binary_sample(data[:4096]):
        return None
    return data[:MAX_TEXT_SCAN_BYTES].decode("utf-8", errors="replace")


def _forbidden_tracked_path(rel_path: str) -> str | None:
    normalized = _normalize_path(rel_path).lower()
    name = normalized.rsplit("/", 1)[-1]
    if normalized == ".env.example":
        return None
    if normalized in FORBIDDEN_EXACT_PATHS:
        return "runtime metadata must not be tracked"
    if name in FORBIDDEN_EXACT_NAMES:
        return "sensitive runtime file must not be tracked"
    if normalized.endswith(FORBIDDEN_SUFFIXES):
        return "database files must not be tracked"
    if normalized.startswith(FORBIDDEN_PREFIXES):
        return "workspace, output, raw data, or uploaded package path must not be tracked"
    return None


def _scan_text(rel_path: str, text: str) -> list[Issue]:
    issues: list[Issue] = []
    for name, pattern in SECRET_PATTERNS:
        for match in pattern.finditer(text):
            issues.append(
                Issue(
                    "secret",
                    f"{rel_path}:{_line_number(text, match.start())} possible {name}; value redacted",
                )
            )
    if _is_config_file(rel_path):
        for match in CONFIG_SECRET_ASSIGNMENT.finditer(text):
            key = match.group(1)
            value = match.group(2)
            if key.endswith("_BASE_URL") or key.endswith("_AVAILABLE_MODELS"):
                continue
            if _is_placeholder(value):
                continue
            issues.append(
                Issue(
                    "secret_assignment",
                    f"{rel_path}:{_line_number(text, match.start())} possible real value for {key}; value redacted",
                )
            )
    return issues


def _scan_env_example() -> list[Issue]:
    env_example = PROJECT_ROOT / ".env.example"
    if not env_example.exists():
        return [Issue("missing_env_example", ".env.example is missing")]
    text = env_example.read_text(encoding="utf-8", errors="replace")
    return _scan_text(".env.example", text)


def _scan_forbidden_tracked_paths(tracked_files: Iterable[str]) -> list[Issue]:
    issues: list[Issue] = []
    for rel_path in tracked_files:
        reason = _forbidden_tracked_path(rel_path)
        if reason:
            issues.append(Issue("tracked_runtime_data", f"{_normalize_path(rel_path)}: {reason}"))
    return issues


def _scan_large_files(files: Iterable[str], *, max_file_mb: int) -> list[Issue]:
    max_bytes = max(1, max_file_mb) * 1024 * 1024
    issues: list[Issue] = []
    for rel_path in files:
        normalized = _normalize_path(rel_path)
        if normalized.startswith(LARGE_FILE_ALLOW_PREFIXES):
            continue
        path = PROJECT_ROOT / normalized
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > max_bytes:
            issues.append(
                Issue(
                    "large_file",
                    f"{normalized}: file is {size / 1024 / 1024:.1f} MB, above {max_file_mb} MB",
                )
            )
    return issues


def _scan_workspace_files(files: Iterable[str]) -> list[Issue]:
    issues: list[Issue] = []
    for rel_path in files:
        normalized = _normalize_path(rel_path)
        path = PROJECT_ROOT / normalized
        if not path.is_file():
            continue
        text = _read_text_for_scan(path)
        if text is None:
            continue
        issues.extend(_scan_text(normalized, text))
    return issues


def _scan_history_paths() -> list[Issue]:
    result = _run_git(["log", "--all", "--name-only", "--format="])
    if result.returncode != 0:
        return [Issue("git_history_unavailable", "git history path scan failed")]
    seen: set[str] = set()
    issues: list[Issue] = []
    for raw in result.stdout.decode("utf-8", errors="replace").splitlines():
        rel_path = _normalize_path(raw.strip())
        if not rel_path or rel_path in seen:
            continue
        seen.add(rel_path)
        reason = _forbidden_tracked_path(rel_path)
        if reason:
            issues.append(Issue("history_runtime_data", f"{rel_path}: present in git history; {reason}"))
    return issues


def _scan_history_secrets() -> list[Issue]:
    commits_result = _run_git(["rev-list", "--all"])
    if commits_result.returncode != 0:
        return [Issue("git_history_unavailable", "git history secret scan failed")]
    issues: list[Issue] = []
    for commit in commits_result.stdout.decode("ascii", errors="ignore").splitlines():
        if not commit:
            continue
        grep_result = _run_git(["grep", "-I", "-n", "-E", HISTORY_GREP_PATTERN, commit])
        if grep_result.returncode not in {0, 1}:
            continue
        if grep_result.returncode == 1:
            continue
        for line in grep_result.stdout.decode("utf-8", errors="replace").splitlines():
            parts = line.split(":", 3)
            if len(parts) >= 3:
                path = parts[1]
                line_no = parts[2]
                issues.append(
                    Issue(
                        "history_secret",
                        f"{commit[:12]}:{_normalize_path(path)}:{line_no} possible historical secret; value redacted",
                    )
                )
            else:
                issues.append(Issue("history_secret", f"{commit[:12]}: possible historical secret; value redacted"))
    return issues


def collect_issues(*, include_history: bool, max_file_mb: int) -> list[Issue]:
    tracked_files = _git_paths(["ls-files", "-z"])
    workspace_files = _git_paths(["ls-files", "-z", "--cached", "--others", "--exclude-standard"])
    issues: list[Issue] = []
    issues.extend(_scan_env_example())
    issues.extend(_scan_forbidden_tracked_paths(tracked_files))
    issues.extend(_scan_large_files(tracked_files, max_file_mb=max_file_mb))
    issues.extend(_scan_workspace_files(workspace_files))
    if include_history:
        issues.extend(_scan_history_paths())
        issues.extend(_scan_history_secrets())
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan RamanAgent for secrets and tracked runtime data.")
    parser.add_argument("--include-history", action="store_true", help="also scan readable git history")
    parser.add_argument("--max-file-mb", type=int, default=int(os.getenv("MAX_TRACKED_FILE_MB", DEFAULT_MAX_FILE_MB)))
    args = parser.parse_args(argv)

    issues = collect_issues(include_history=args.include_history, max_file_mb=args.max_file_mb)
    if issues:
        print("Repository security scan failed:")
        for issue in issues:
            print(f"- [{issue.code}] {issue.message}")
        return 1
    print("Repository security scan passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
