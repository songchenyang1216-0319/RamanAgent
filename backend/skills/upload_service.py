"""Skill 上传与用户上传记录管理。"""

from __future__ import annotations

import json
import logging
import re
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from raman_core.methanol.config import PROJECT_ROOT

from .uploaded_package_skill import discover_uploaded_package_skills


logger = logging.getLogger(__name__)
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


def _normalize_skill_key(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip().lower()


def _is_within_path(child: Path, parent: Path) -> bool:
    child_resolved = Path(child).resolve()
    parent_resolved = Path(parent).resolve()
    return child_resolved == parent_resolved or parent_resolved in child_resolved.parents


def _safe_delete_path(path: Path, allowed_root: Path) -> bool:
    if not _is_within_path(path, allowed_root):
        raise ValueError(f"拒绝删除不在允许范围内的路径：{path}")

    if path.is_dir():
        shutil.rmtree(path)
        return True

    if path.exists():
        path.unlink()
        return True

    return False


def _record_path_value(path: Path) -> str:
    resolved = Path(path).resolve()
    try:
        return str(resolved.relative_to(PROJECT_ROOT)).replace("\\", "/")
    except ValueError:
        return str(resolved).replace("\\", "/")


def _resolve_record_path(value: str) -> Path:
    path = Path(str(value or ""))
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def _resolve_discovered_metadata_from_extract_dir(extract_dir_value: str) -> dict[str, Any]:
    """兼容旧上传记录：根据 extract_dir 反查当前扫描到的 Skill 元数据。"""
    if not extract_dir_value:
        return {}
    try:
        absolute_extract_dir = str(_resolve_record_path(extract_dir_value).resolve()).replace("\\", "/")
    except Exception:
        return {}
    if not absolute_extract_dir:
        return {}

    for skill in discover_uploaded_package_skills(SKILL_EXTRACT_DIR):
        package_dir = str(skill.package_dir.resolve()).replace("\\", "/")
        if package_dir.startswith(absolute_extract_dir):
            return skill.metadata(include_actions=True)
    return {}


def list_uploaded_skills() -> list[dict[str, Any]]:
    """返回用户上传 Skill 的展示元数据。"""
    discovered_skills = discover_uploaded_package_skills(SKILL_EXTRACT_DIR)
    discovered = {skill.name: skill.metadata(include_actions=True) for skill in discovered_skills}
    items = []
    for record in _read_upload_meta():
        extract_dir = str(record.get("extract_dir") or "")
        absolute_extract_dir = str(_resolve_record_path(extract_dir).resolve()).replace("\\", "/") if extract_dir else ""
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
                "skill_mode": str(discovered_metadata.get("skill_mode") or record.get("skill_mode") or "invalid"),
                "has_skill_md": bool(discovered_metadata.get("has_skill_md", record.get("has_skill_md", False))),
                "has_manifest": bool(discovered_metadata.get("has_manifest", record.get("has_manifest", False))),
                "has_scripts": bool(discovered_metadata.get("has_scripts", record.get("has_scripts", False))),
                "entrypoint": str(discovered_metadata.get("entrypoint") or record.get("entrypoint") or ""),
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
    has_skill_md = (extract_dir / "SKILL.md").exists()
    has_manifest = (extract_dir / "manifest.json").exists() or (extract_dir / "metadata.json").exists()
    has_scripts = any(item.is_file() for item in (extract_dir / "scripts").rglob("*")) if (extract_dir / "scripts").exists() else False
    runtime_skill_mode = runtime_skill.skill_mode if runtime_skill is not None else ("prompt_only" if has_skill_md else "invalid")
    logger.info(
        "Skill upload parsed: skill_name=%s skill_mode=%s has_skill_md=%s has_manifest=%s has_scripts=%s entrypoint=%s",
        runtime_skill.name if runtime_skill is not None else safe_name,
        runtime_skill_mode,
        has_skill_md,
        has_manifest,
        has_scripts,
        runtime_skill.entrypoint if runtime_skill is not None else "",
    )
    if runtime_skill is None:
        archive_path.unlink(missing_ok=True)
        shutil.rmtree(extract_dir, ignore_errors=True)
        raise ValueError("上传的 Skill 包缺少 SKILL.md 或 manifest.json，无法识别。")
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
        "skill_mode": runtime_skill_mode,
        "has_skill_md": has_skill_md,
        "has_manifest": has_manifest,
        "has_scripts": has_scripts,
        "entrypoint": runtime_skill.entrypoint if runtime_skill is not None else "",
        "upload_status": upload_status,
        "uploaded_at": datetime.now().isoformat(timespec="seconds"),
        "archive_path": _record_path_value(archive_path),
        "extract_dir": _record_path_value(extract_dir),
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
        "skill_mode": runtime_skill_mode,
        "message": "提示词型 Skill 已安装，可用于增强大模型回答。" if runtime_skill_mode == "prompt_only" else "可执行型 Skill 已安装，可用于脚本执行。",
        "reload_required": True,
        "archive_path": record["archive_path"],
        "extract_dir": record["extract_dir"],
    }


def delete_uploaded_skill(skill_name: str) -> dict[str, Any]:
    """删除一个已上传的 Skill。"""
    _ensure_dirs()
    normalized_target = _normalize_skill_key(skill_name)
    if not normalized_target:
        raise ValueError("Skill 名称不能为空。")

    records = _read_upload_meta()
    matched_records: list[dict[str, Any]] = []
    for record in records:
        discovered_metadata = _resolve_discovered_metadata_from_extract_dir(str(record.get("extract_dir") or ""))
        record_keys = {
            _normalize_skill_key(record.get("name")),
            _normalize_skill_key(record.get("skill_name")),
            _normalize_skill_key(record.get("display_name")),
            _normalize_skill_key(discovered_metadata.get("name")),
            _normalize_skill_key(discovered_metadata.get("display_name")),
        }
        if normalized_target in record_keys:
            matched_records.append(record)

    if not matched_records:
        raise KeyError(f"未找到可删除的已上传 Skill: {skill_name}")

    archive_root = SKILL_UPLOAD_DIR.resolve()
    extract_root = SKILL_EXTRACT_DIR.resolve()
    deleted_archives: list[str] = []
    deleted_extract_dirs: list[str] = []
    affected_skill_names: set[str] = set()

    for record in matched_records:
        affected_skill_names.update(
            {
                str(record.get("name") or "").strip(),
                str(record.get("skill_name") or "").strip(),
            }
        )
        archive_path_value = str(record.get("archive_path") or "").strip()
        if archive_path_value:
            archive_path = _resolve_record_path(archive_path_value)
            if archive_path.exists():
                _safe_delete_path(archive_path, archive_root)
                deleted_archives.append(_record_path_value(archive_path))
        extract_dir_value = str(record.get("extract_dir") or "").strip()
        if extract_dir_value:
            extract_dir = _resolve_record_path(extract_dir_value)
            if extract_dir.exists():
                _safe_delete_path(extract_dir, extract_root)
                deleted_extract_dirs.append(_record_path_value(extract_dir))

    remaining_records = [record for record in records if record not in matched_records]
    _write_upload_meta(remaining_records)

    try:
        from .registry import remove_skill_config_entries, skill_registry

        builtin_skill_names = {str(name) for name in skill_registry.keys()}
        remaining_uploaded_skill_names = {
            str(record.get("skill_name") or record.get("name") or "").strip()
            for record in remaining_records
            if str(record.get("skill_name") or record.get("name") or "").strip()
        }
        removable_skill_names = {
            skill_name
            for skill_name in affected_skill_names
            if skill_name and skill_name not in builtin_skill_names and skill_name not in remaining_uploaded_skill_names
        }
        config_result = remove_skill_config_entries(removable_skill_names)
    except Exception:
        config_result = {"removed_skill_names": [], "success": False}

    return {
        "success": True,
        "message": "Skill 已删除",
        "reload_required": True,
        "skill_name": skill_name,
        "deleted_records": [
            {
                "name": str(record.get("name") or ""),
                "skill_name": str(record.get("skill_name") or ""),
                "display_name": str(record.get("display_name") or ""),
            }
            for record in matched_records
        ],
        "deleted_archives": deleted_archives,
        "deleted_extract_dirs": deleted_extract_dirs,
        "config_cleanup": config_result,
    }
