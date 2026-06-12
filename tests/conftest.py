from __future__ import annotations

import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

sys.dont_write_bytecode = True

os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("VECTOR_DB_PROVIDER", "mock")
os.environ.setdefault("EMBEDDING_PROVIDER", "mock")
os.environ.setdefault("EMBEDDING_MODEL", "mock-hash-embedding")
os.environ.setdefault("RAG_ENABLE_RERANK", "true")
os.environ.setdefault("PDF_EXPORT_PROVIDER", "none")
os.environ.setdefault("OCR_PROVIDER", "none")
