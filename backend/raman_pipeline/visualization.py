"""Plot helpers for Raman pipeline runs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from backend.utils.plot_style import apply_chinese_plot_style
from raman_core.methanol.config import OUTPUT_DIR, PROJECT_ROOT, ensure_dirs


def web_url(path: Path) -> str:
    try:
        return "/" + str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)


def save_spectrum_plot(data: dict[str, Any], run_id: str, step_id: str, title: str) -> dict[str, Any] | None:
    if data.get("wavenumber") is None or data.get("intensity") is None:
        return None
    x = np.asarray(data["wavenumber"], dtype=float)
    y = np.asarray(data["intensity"], dtype=float)
    if x.size < 2 or y.size < 2 or x.size != y.size:
        return None
    ensure_dirs()
    out_dir = OUTPUT_DIR / "raman_pipeline" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{step_id}.png"
    apply_chinese_plot_style()
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(x, y, linewidth=1.2)
    ax.set_title(title)
    ax.set_xlabel("Wavenumber")
    ax.set_ylabel("Intensity")
    ax.grid(alpha=0.22)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return {
        "type": "image",
        "title": title,
        "path": str(path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "url": web_url(path),
    }

