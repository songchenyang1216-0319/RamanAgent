from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import joblib

from raman_core.methanol.config import ARTIFACT_DIR


def export_model(model: Any, *, model_type: str, target: str) -> str:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    path = ARTIFACT_DIR / f"trained_{target}_{model_type}_{uuid4().hex[:8]}.joblib"
    joblib.dump(model, path)
    return str(path)

