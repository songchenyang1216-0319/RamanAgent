from __future__ import annotations

import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"(?im)^(?:[A-Z0-9_]*(?:API[_-]?KEY|TOKEN|SECRET)[A-Z0-9_]*)[^\S\r\n]*=[^\S\r\n]*(?!$)(?!your_)(?!changeme)(?!example)(?!placeholder)([A-Za-z0-9_\-]{16,})[^\S\r\n]*$"),
]


def main() -> int:
    issues: list[str] = []
    env_example = PROJECT_ROOT / ".env.example"
    gitignore = PROJECT_ROOT / ".gitignore"

    if not env_example.exists():
        issues.append(".env.example 不存在。")
    else:
        text = env_example.read_text(encoding="utf-8", errors="replace")
        for pattern in SECRET_PATTERNS:
            for match in pattern.finditer(text):
                snippet = match.group(0).split("=", 1)[0].strip()
                issues.append(f".env.example 疑似包含真实密钥或 token：{snippet}")

    if not gitignore.exists():
        issues.append(".gitignore 不存在。")
    else:
        gitignore_text = gitignore.read_text(encoding="utf-8", errors="replace")
        if ".env" not in gitignore_text:
            issues.append(".gitignore 未忽略 .env。")
        if "storage/" not in gitignore_text and "outputs/" not in gitignore_text:
            issues.append(".gitignore 未忽略运行产物目录 storage/ 或 outputs/。")

    if (PROJECT_ROOT / ".env").exists():
        print("提示：本地存在 .env，请确认不要提交真实密钥。")

    if issues:
        print("安全检查失败：")
        for issue in issues:
            print(f"- {issue}")
        return 1

    print("安全检查通过：未在 .env.example 中发现明显真实密钥，.env 已被忽略。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
