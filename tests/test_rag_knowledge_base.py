from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.agent.message_normalizer import MessageNormalizer
from backend.services.file_converter import FileConverterService
from backend.services.knowledge_base.knowledge_base_permissions import KnowledgeBasePermissionService


def test_message_normalizer_keeps_multi_file_ids():
    normalized = MessageNormalizer().normalize(
        {
            "message": "比较这些文件",
            "conversation_id": "conv_multi",
            "files": [
                {"file_id": "f1", "path": "storage/workspaces/u/conv_multi/uploads/a.txt"},
                {"file_id": "f2", "path": "storage/workspaces/u/conv_multi/uploads/b.md"},
            ],
        }
    )
    assert normalized.has_file is True
    assert normalized.file_ids == ["f1", "f2"]
    assert len(normalized.selected_files) == 2
    assert normalized.file_name == "a.txt"


def test_knowledge_base_public_read_without_write():
    service = KnowledgeBasePermissionService()
    kb = {"knowledge_base_id": "kb_public", "owner_user_id": "owner", "visibility": "public"}
    assert service.can_read(kb, "reader") is True
    assert service.can_write(kb, "reader") is False


def test_file_converter_format_aliases():
    converter = FileConverterService()
    assert converter._normalize_format("Markdown") == "md"
    assert converter._normalize_format(".excel") == "xlsx"
    assert converter._normalize_format("word") == "docx"
