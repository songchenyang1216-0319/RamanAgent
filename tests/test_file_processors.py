from __future__ import annotations

from pathlib import Path
import sys
from zipfile import ZipFile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.services.file_processor import FileProcessorRegistry


def test_text_processor_creates_searchable_chunks(tmp_path: Path):
    path = tmp_path / "note.txt"
    path.write_text("第一段：这是一个关于 Agent 平台的说明。\n\n第二段：支持文件问答。", encoding="utf-8")
    registry = FileProcessorRegistry()
    result = registry.process(path, file_id="note-file", user_id="test-user", conversation_id="test-conv")
    assert result.success is True
    assert result.chunks
    chunks = registry.search_chunks(user_id="test-user", conversation_id="test-conv", query="文件问答", file_ids=["note-file"])
    assert chunks
    assert "文件问答" in chunks[0]["text"]


def test_zip_processor_blocks_zip_slip_entries(tmp_path: Path):
    path = tmp_path / "sample.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr("safe/readme.txt", "ok")
        archive.writestr("../evil.txt", "blocked")
    result = FileProcessorRegistry().process(path, file_id="zip-file", user_id="test-user", conversation_id="zip-conv")
    assert result.success is True
    assert result.metadata["safe_file_count"] == 1
    assert "../evil.txt" in result.metadata["blocked_entries"]
