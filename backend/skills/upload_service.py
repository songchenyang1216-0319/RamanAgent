"""Skill 上传与用户上传记录管理。"""

from __future__ import annotations

import json
import re
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from raman_core.methanol.config import PROJECT_ROOT

from .uploaded_package_skill import discover_uploaded_package_skills


SKILL_UPLOAD_DIR = PROJECT_ROOT / "backend" / "data" / "skill_uploads"
SKILL_EXTRACT_DIR = PROJECT_ROOT / "backend" / "skills" / "custom"
SKILL_UPLOAD_META_PATH = PROJECT_ROOT / "backend" / "data" / "uploaded_skills.json"


def _ensure_dirs() -> None:
    SKILL_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    SKILL_EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
    SKILL_UPLOAD_META_PATH.parent.mkdir(parents=True, exist_ok=True)


def _safe_skill_name(filename: str) -> str:
    stem = Path(filename).stem.strip() or "uploaded_skill"
    normalized = re.sub(r"[^0-9A-Za-z_\-]+", "_", stem).strip("_").lower()
    return normalized or "uploaded_skill"


def _read_upload_meta() -> list[dict[str, Any]]:
    _ensure_dirs()
    if not SKILL_UPLOAD_META_PATH.exists():
        return []
    try:
        data = json.loads(SKILL_UPLOAD_META_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _write_upload_meta(records: list[dict[str, Any]]) -> None:
    _ensure_dirs()
    SKILL_UPLOAD_META_PATH.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _replace_record(records: list[dict[str, Any]], record: dict[str, Any]) -> list[dict[str, Any]]:
    updated = [item for item in records if str(item.get("name")) != str(record.get("name"))]
    updated.insert(0, record)
    return updated


def list_uploaded_skills() -> list[dict[str, Any]]:
    """返回用户上传 Skill 的展示元数据。"""
    discovered_skills = discover_uploaded_package_skills(SKILL_EXTRACT_DIR)
    discovered = {skill.name: skill.metadata(include_actions=True) for skill in discovered_skills}
    items = []
    for record in _read_upload_meta():
        extract_dir = str(record.get("extract_dir") or "")
        absolute_extract_dir = str((PROJECT_ROOT / extract_dir).resolve()).replace("\\", "/") if extract_dir else ""
        discovered_metadata = dict(discovered.get(str(record.get("skill_name") or "")) or {})
        if not discovered_metadata and absolute_extract_dir:
            for skill in discovered_skills:
                package_dir = str(skill.package_dir.resolve()).replace("\\", "/")
                if package_dir.startswith(absolute_extract_dir):
                    discovered_metadata = skill.metadata(include_actions=True)
                    break
        skill_name = str(discovered_metadata.get("name") or record.get("skill_name") or record.get("name") or "uploaded_skill")
        items.append(
            {
                "name": skill_name,
                "display_name": str(discovered_metadata.get("display_name") or record.get("display_name") or skill_name),
                "description": str(discovered_metadata.get("description") or record.get("description") or "用户上传的 Skill 压缩包，等待刷新或重启后进一步加载。"),
                "category": "用户上传",
                "enabled": bool(record.get("enabled", True)),
                "available": bool(discovered_metadata) or bool(record.get("available", False)),
                "unavailable_reason": str(record.get("unavailable_reason") or ("" if discovered_metadata else "该 Skill 已上传，但当前仅完成保存与解压，尚未自动注册。")),
                "version": str(discovered_metadata.get("version") or record.get("version") or "uploaded"),
                "requires_file": bool(discovered_metadata.get("requires_file", False)),
                "supported_file_types": list(discovered_metadata.get("supported_file_types") or []),
                "usage": str(discovered_metadata.get("usage") or record.get("usage") or "如需正式启用，请在后端补充注册逻辑后刷新或重启服务。"),
                "actions": list(discovered_metadata.get("actions") or []),
                "source": "uploaded",
                "upload_status": str(record.get("upload_status") or ("loaded" if discovered_metadata else "pending_load")),
                "uploaded_at": str(record.get("uploaded_at") or ""),
                "archive_path": str(record.get("archive_path") or ""),
                "extract_dir": str(record.get("extract_dir") or ""),
                "triggers": list(discovered_metadata.get("triggers") or []),
                "capabilities": list(discovered_metadata.get("capabilities") or []),
                "expected_markers": list(discovered_metadata.get("expected_markers") or []),
            }
        )
    for discovered_name, discovered_metadata in discovered.items():
        if any(str(item.get("name")) == discovered_name for item in items):
            continue
        items.append(
            {
                **discovered_metadata,
                "enabled": True,
                "available": True,
                "source": "uploaded",
                "upload_status": "loaded",
                "uploaded_at": "",
                "archive_path": "",
                "extract_dir": str(Path(discovered_metadata.get("package_dir") or "")).replace("\\", "/"),
            }
        )
    return items


def save_uploaded_skill(filename: str, content: bytes) -> dict[str, Any]:
    """保存并解压用户上传的 Skill zip。"""
    _ensure_dirs()
    if not filename.lower().endswith(".zip"):
        raise ValueError("仅支持上传 .zip 格式的 Skill 压缩包。")

    safe_name = _safe_skill_name(filename)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_name = f"{safe_name}_{timestamp}.zip"
    archive_path = SKILL_UPLOAD_DIR / archive_name
    archive_path.write_bytes(content)

    if not zipfile.is_zipfile(archive_path):
        archive_path.unlink(missing_ok=True)
        raise ValueError("上传文件不是有效的 zip 压缩包。")

    extract_dir = SKILL_EXTRACT_DIR / safe_name
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(archive_path, "r") as zf:
        for member in zf.infolist():
            member_path = Path(member.filename)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise ValueError("zip 包含非法路径，已拒绝处理。")
        zf.extractall(extract_dir)

    discovered = discover_uploaded_package_skills(extract_dir)
    runtime_skill = discovered[0] if discovered else None
    runtime_name = runtime_skill.name if runtime_skill is not None else safe_name
    runtime_display_name = runtime_skill.display_name if runtime_skill is not None else safe_name
    runtime_version = runtime_skill.version if runtime_skill is not None else "uploaded"
    runtime_description = runtime_skill.description if runtime_skill is not None else "用户上传的 Skill 压缩包，已保存并解压，等待后续加载。"
    upload_status = "loaded" if runtime_skill is not None else "pending_load"
    unavailable_reason = "" if runtime_skill is not None else "当前实现已完成保存与解压，需刷新 Skills 列表；若未接入自动注册，则重启后再加载。"

    record = {
        "name": safe_name,
        "skill_name": runtime_name,
        "display_name": runtime_display_name,
        "description": runtime_description,
        "version": runtime_version,
        "upload_status": upload_status,
        "uploaded_at": datetime.now().isoformat(timespec="seconds"),
        "archive_path": str(archive_path.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "extract_dir": str(extract_dir.relative_to(PROJECT_ROOT)).replace("\\", "/"),
        "reload_required": True,
        "unavailable_reason": unavailable_reason,
        "usage": "上传成功后会在 Skills 列表中显示为 source: uploaded / 待加载。",
        "source": "uploaded",
    }
    records = _replace_record(_read_upload_meta(), record)
    _write_upload_meta(records)
    return {
        "success": True,
        "skill_name": runtime_name,
        "message": "Skill 上传成功，已加入待加载列表",
        "reload_required": True,
        "archive_path": record["archive_path"],
        "extract_dir": record["extract_dir"],
    }
