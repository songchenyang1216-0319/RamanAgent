"""Preflight checks for local demo and production-like startup.

Run with:
    python -m scripts.preflight_check
"""

from __future__ import annotations

import importlib.util
import os
import re
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_DIRS = [
    "data/demo",
    "storage",
    "storage/vector_db",
    "outputs",
    "outputs/results",
    "outputs/reports",
    "artifacts",
]
PLACEHOLDER_RE = re.compile(r"^(your_|sk-|xxx|test|demo|placeholder|changeme|none$|null$)", re.I)


class Reporter:
    def __init__(self) -> None:
        self.errors = 0
        self.warnings = 0

    def pass_(self, message: str) -> None:
        print(f"PASS    {message}")

    def warning(self, message: str) -> None:
        self.warnings += 1
        print(f"WARNING {message}")

    def error(self, message: str) -> None:
        self.errors += 1
        print(f"ERROR   {message}")


def _env(name: str, default: str = "") -> str:
    return str(os.getenv(name, default)).strip()


def _looks_placeholder(value: str) -> bool:
    value = str(value or "").strip()
    if not value:
        return False
    return bool(PLACEHOLDER_RE.search(value.lower())) or "your_" in value.lower()


def _sqlite_path(database_url: str) -> Path:
    if database_url.startswith("sqlite:///"):
        return Path(database_url.removeprefix("sqlite:///"))
    if database_url.startswith("sqlite://"):
        return Path(database_url.removeprefix("sqlite://"))
    return Path(database_url or "outputs/results/ramanagent.db")


def _check_python(reporter: Reporter) -> None:
    version = sys.version_info
    if version >= (3, 10):
        reporter.pass_(f"Python {version.major}.{version.minor}.{version.micro}")
    else:
        reporter.error("Python 版本过低，建议使用 3.10+。")


def _check_dirs(reporter: Reporter) -> None:
    for rel in REQUIRED_DIRS:
        path = PROJECT_ROOT / rel
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            reporter.pass_(f"目录可写：{rel}")
        except Exception as exc:
            reporter.error(f"目录不可写：{rel}，原因：{exc}")


def _check_database(reporter: Reporter) -> None:
    database_url = _env("DATABASE_URL", "sqlite:///outputs/results/ramanagent.db")
    if not database_url.startswith("sqlite"):
        reporter.warning("当前代码运行时只内置 SQLite；非 SQLite DATABASE_URL 属于预留配置。")
        return
    path = _sqlite_path(database_url)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        connection.execute("CREATE TABLE IF NOT EXISTS preflight_probe (id INTEGER PRIMARY KEY, created_at TEXT)")
        connection.commit()
        connection.close()
        reporter.pass_(f"SQLite 可初始化：{path.relative_to(PROJECT_ROOT) if PROJECT_ROOT in path.parents else path}")
    except Exception as exc:
        reporter.error(f"SQLite 不可用：{exc}")


def _check_model_config(reporter: Reporter) -> None:
    provider = _env("LLM_PROVIDER", "sensenova")
    api_key = _env(f"{provider.upper()}_API_KEY") or _env("LLM_API_KEY")
    if api_key and not _looks_placeholder(api_key):
        reporter.pass_(f"模型平台已配置：{provider}")
    else:
        reporter.warning(f"模型平台 {provider} 未配置真实 API Key；普通聊天会使用本地降级或返回明确提示。")


def _check_embedding_and_vector(reporter: Reporter) -> None:
    app_env = _env("APP_ENV", "development").lower()
    embedding_provider = _env("EMBEDDING_PROVIDER", "mock").lower()
    embedding_model = _env("EMBEDDING_MODEL", "mock-hash-embedding")
    vector_provider = _env("VECTOR_DB_PROVIDER", "mock").lower()
    vector_dir = PROJECT_ROOT / _env("VECTOR_DB_DIR", "storage/vector_db")

    if app_env == "production" and embedding_provider == "mock":
        reporter.error("production 环境不能使用 EMBEDDING_PROVIDER=mock。")
    elif embedding_provider == "mock":
        reporter.warning("当前使用 mock embedding，仅适合开发/CI；demo/production 建议 local + BAAI/bge-small-zh-v1.5。")
    elif embedding_provider == "local":
        if importlib.util.find_spec("sentence_transformers") is None:
            reporter.error("EMBEDDING_PROVIDER=local 但未安装 sentence-transformers。")
        else:
            reporter.pass_(f"Local embedding 依赖可用：{embedding_model}")
    else:
        reporter.warning(f"Embedding provider={embedding_provider} 需要外部服务配置，请确认 API Key/Base URL。")

    if vector_provider == "chroma":
        vector_dir.mkdir(parents=True, exist_ok=True)
        if importlib.util.find_spec("chromadb") is None:
            message = "VECTOR_DB_PROVIDER=chroma 但未安装 chromadb；pip install -r requirements.txt 后重试。"
            if app_env == "production":
                reporter.error(message)
            else:
                reporter.warning(message)
        else:
            reporter.pass_(f"Chroma 依赖可用，目录：{vector_dir.relative_to(PROJECT_ROOT)}")
    elif vector_provider == "mock":
        reporter.warning("当前使用 mock vector store，仅适合开发/CI。")
    else:
        reporter.error(f"未知 VECTOR_DB_PROVIDER：{vector_provider}")


def _check_ocr(reporter: Reporter) -> None:
    provider = _env("OCR_PROVIDER", "auto").lower()
    if provider in {"none", "off", "disabled"}:
        reporter.pass_("OCR 已关闭；扫描件 PDF/图片不会自动识别文字。")
    elif provider in {"auto", "tesseract"}:
        reporter.warning("OCR 需要额外系统依赖 Tesseract/Poppler；未安装时应使用普通文本 PDF/DOCX/MD 演示。")
    else:
        reporter.warning(f"OCR_PROVIDER={provider} 需要确认对应依赖。")


def _check_demo_files(reporter: Reporter) -> None:
    expected = ["raman_demo_valid.csv", "raman_demo_with_noise.csv", "raman_demo_invalid.csv"]
    demo_dir = PROJECT_ROOT / "data" / "demo"
    for name in expected:
        if (demo_dir / name).exists():
            reporter.pass_(f"Demo 文件存在：data/demo/{name}")
        else:
            reporter.warning(f"Demo 文件缺失：data/demo/{name}")


def _check_placeholder_keys(reporter: Reporter) -> None:
    names = [name for name in os.environ if name.endswith("API_KEY") or name.endswith("TOKEN") or name.endswith("SECRET")]
    placeholders = [name for name in sorted(names) if _looks_placeholder(os.getenv(name, ""))]
    if placeholders:
        reporter.warning("检测到占位密钥：" + ", ".join(placeholders[:12]))
    else:
        reporter.pass_("未发现明显占位 API Key。")


def main() -> int:
    load_dotenv(PROJECT_ROOT / ".env")
    reporter = Reporter()
    print("RamanAgent preflight check")
    print(f"Project root: {PROJECT_ROOT}")
    _check_python(reporter)
    _check_dirs(reporter)
    _check_database(reporter)
    _check_model_config(reporter)
    _check_embedding_and_vector(reporter)
    _check_ocr(reporter)
    _check_demo_files(reporter)
    _check_placeholder_keys(reporter)
    print(f"Summary: errors={reporter.errors}, warnings={reporter.warnings}")
    return 1 if reporter.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
