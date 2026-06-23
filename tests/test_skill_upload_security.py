from __future__ import annotations

from io import BytesIO
from pathlib import Path
import zipfile

import pytest

from backend.skills import upload_service


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buffer.getvalue()


def test_skill_upload_rejects_zip_path_traversal(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(upload_service, "SKILL_UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(upload_service, "SKILL_EXTRACT_DIR", tmp_path / "custom")
    monkeypatch.setattr(upload_service, "SKILL_UPLOAD_META_PATH", tmp_path / "uploaded_skills.json")

    content = _zip_bytes({"../escape.txt": b"nope"})

    with pytest.raises(ValueError, match="非法路径"):
        upload_service.save_uploaded_skill("escape.zip", content)

    assert not (tmp_path / "escape.txt").exists()


def test_skill_upload_rejects_dangerous_file_extension(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(upload_service, "SKILL_UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(upload_service, "SKILL_EXTRACT_DIR", tmp_path / "custom")
    monkeypatch.setattr(upload_service, "SKILL_UPLOAD_META_PATH", tmp_path / "uploaded_skills.json")

    content = _zip_bytes({"skill/SKILL.md": b"# Demo\n", "skill/run.ps1": b"Write-Host bad"})

    with pytest.raises(ValueError, match="不允许的文件类型"):
        upload_service.save_uploaded_skill("danger.zip", content)
