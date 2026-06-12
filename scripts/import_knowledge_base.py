from __future__ import annotations

import argparse
import mimetypes
import shutil
from pathlib import Path
import sys
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.services.file_processor import FileProcessorRegistry  # noqa: E402
from backend.services.knowledge_base import KnowledgeBaseIndexer, KnowledgeBaseService  # noqa: E402
from backend.services.knowledge_base.knowledge_base_file_service import KB_ROOT, KnowledgeBaseFileService  # noqa: E402
from backend.services.workspace_manager import safe_filename, safe_segment  # noqa: E402


def iter_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return [item for item in path.rglob("*") if item.is_file()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Import local files into a RamanAgent knowledge base.")
    parser.add_argument("path", help="File or directory to import")
    parser.add_argument("--user-id", default="default_user")
    parser.add_argument("--name", default="导入知识库")
    parser.add_argument("--description", default="通过 scripts/import_knowledge_base.py 导入")
    parser.add_argument("--kb-id", default="")
    args = parser.parse_args()

    source = Path(args.path).resolve()
    if not source.exists():
        raise SystemExit(f"路径不存在: {source}")

    kb_service = KnowledgeBaseService()
    if args.kb_id:
        kb = kb_service.get_knowledge_base(args.user_id, args.kb_id, is_admin=True)
    else:
        kb = kb_service.create_knowledge_base(args.user_id, args.name, args.description)
    kb_id = str(kb["knowledge_base_id"])
    owner = str(kb["owner_user_id"])
    target_dir = KB_ROOT / safe_segment(owner) / safe_segment(kb_id) / "sources"
    target_dir.mkdir(parents=True, exist_ok=True)

    processors = FileProcessorRegistry()
    indexer = KnowledgeBaseIndexer()
    file_service = KnowledgeBaseFileService()
    imported = 0
    failed = 0
    for item in iter_files(source):
        kb_file_id = f"kbf_{uuid4().hex[:12]}"
        safe_name = safe_filename(item.name, fallback="knowledge-file")
        target = target_dir / f"{Path(safe_name).stem}_{uuid4().hex[:8]}{Path(safe_name).suffix}"
        shutil.copy2(item, target)
        processor = processors.get_processor(target)
        processed = processor.process(target, file_id=kb_file_id).to_dict() if processor else {"success": False, "chunks": [], "file_type": target.suffix.lower().lstrip("."), "error_message": "不支持的文件类型"}
        chunk_count = 0
        rag_status = "not_supported"
        rag_error = processed.get("error_message")
        if processed.get("success") and processed.get("chunks"):
            chunk_count = indexer.store_processed_chunks(
                owner_user_id=owner,
                knowledge_base_id=kb_id,
                kb_file_id=kb_file_id,
                source_name=item.name,
                source_type=str(processed.get("file_type") or target.suffix.lower().lstrip(".")),
                chunks=list(processed.get("chunks") or []),
            )
            result = indexer.index_knowledge_base_file(owner_user_id=owner, knowledge_base_id=kb_id, kb_file_id=kb_file_id, knowledge_base_name=str(kb.get("name") or ""))
            rag_status = str(result.get("status") or "failed")
            rag_error = result.get("error_message")
        file_service._insert_file(
            kb_file_id=kb_file_id,
            knowledge_base_id=kb_id,
            owner_user_id=owner,
            original_filename=item.name,
            stored_path=str(target.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            file_type=target.suffix.lower().lstrip("."),
            mime_type=mimetypes.guess_type(target.name)[0] or "application/octet-stream",
            size=target.stat().st_size,
            processing_status="success" if processed.get("success") else "failed",
            rag_index_status=rag_status,
            rag_index_error=rag_error,
            chunk_count=chunk_count,
        )
        if processed.get("success"):
            imported += 1
        else:
            failed += 1
            print(f"导入失败: {item.name} - {processed.get('error_message')}")

    print(f"knowledge_base_id={kb_id}")
    print(f"imported={imported} failed={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
