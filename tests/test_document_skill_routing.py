from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.skills.uploaded_package_skill import discover_uploaded_package_skills
from backend.skills.registry import match_uploaded_skill


def test_document_skill_metadata_json_is_discovered(tmp_path: Path):
    package_dir = tmp_path / "document-processing-skill"
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "SKILL.md").write_text("# Document Processing Skill\n\n支持 TXT/PDF/DOCX/PPTX。", encoding="utf-8")
    (package_dir / "metadata.json").write_text(
        json.dumps(
            {
                "name": "document-processing-skill",
                "display_name": "Document Processing Skill",
                "version": "1.0.0",
                "description": "Document processing skill",
                "supported_file_types": [".pdf", ".docx", ".pptx", ".txt", ".md"],
                "task_types": ["extract", "rag_chunk"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    skills = discover_uploaded_package_skills(tmp_path)
    assert len(skills) == 1
    skill = skills[0]
    assert skill.name == "document-processing-skill"
    assert skill.supports_file_suffix(".txt") is True
    assert skill.infer_task_type("帮我分析这个文件", file_suffix=".txt") == "extract"


def test_document_skill_can_be_selected_by_txt_suffix(tmp_path: Path):
    package_dir = tmp_path / "document-processing-skill"
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "SKILL.md").write_text("# Document Processing Skill\n\n支持 TXT/PDF/DOCX/PPTX。", encoding="utf-8")
    (package_dir / "metadata.json").write_text(
        json.dumps(
            {
                "name": "document-processing-skill",
                "display_name": "Document Processing Skill",
                "version": "1.0.0",
                "description": "Document processing skill",
                "supported_file_types": [".pdf", ".docx", ".pptx", ".txt", ".md"],
                "task_types": ["extract", "rag_chunk"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    skill, route_info = match_uploaded_skill("帮我分析一下这个文件", file_suffix=".txt")
    assert skill is not None
    assert skill.name == "document-processing-skill"
    assert route_info is not None
    assert route_info["route"] == "uploaded_skill_match"
    assert "file_type:.txt" in route_info["reason"]
if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        test_document_skill_metadata_json_is_discovered(temp_path)
        test_document_skill_can_be_selected_by_txt_suffix(temp_path)
    print("document skill routing tests passed")
