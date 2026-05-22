"""项目路径与通用配置。"""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_DIR = PROJECT_ROOT / "artifacts"
DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
DEMO_DATA_DIR = DATA_DIR / "demo"
OUTPUT_DIR = PROJECT_ROOT / "outputs"
FIGURE_DIR = OUTPUT_DIR / "figures"
REPORT_DIR = OUTPUT_DIR / "reports"
RESULT_DIR = OUTPUT_DIR / "results"


def ensure_dirs() -> None:
    """确保工程运行所需目录存在。"""
    for path in (
        DATA_DIR,
        RAW_DATA_DIR,
        PROCESSED_DATA_DIR,
        DEMO_DATA_DIR,
        OUTPUT_DIR,
        FIGURE_DIR,
        REPORT_DIR,
        RESULT_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)
