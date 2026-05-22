"""Skill 注册表与启用状态配置。"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from raman_core.methanol.config import PROJECT_ROOT

from .agent_system_skill import AgentSystemSkill
from .base import BaseSkill, SkillResult
from .experiment_report_skill import ExperimentReportSkill
from .methanol_analysis_skill import MethanolAnalysisSkill
from .spectral_file_skill import SpectralFileSkill
from .spectral_preprocessing_skill import SpectralPreprocessingSkill
from .spectral_visualization_skill import SpectralVisualizationSkill
from .upload_service import list_uploaded_skills
from .uploaded_package_skill import UploadedPackageSkill, discover_uploaded_package_skills


skill_registry: dict[str, BaseSkill] = {}
SKILLS_CONFIG_PATH = PROJECT_ROOT / "backend" / "data" / "skills_config.json"
CUSTOM_SKILL_ROOT = PROJECT_ROOT / "backend" / "skills" / "custom"


def register_skill(skill: BaseSkill) -> BaseSkill:
    """注册大 Skill。"""
    skill_registry[str(skill.name)] = skill
    return skill


def _load_uploaded_skill_registry() -> dict[str, BaseSkill]:
    uploaded_skills = discover_uploaded_package_skills(CUSTOM_SKILL_ROOT)
    return {str(skill.name): skill for skill in uploaded_skills}


def _combined_skill_registry() -> dict[str, BaseSkill]:
    combined = dict(skill_registry)
    combined.update(_load_uploaded_skill_registry())
    return combined


def get_skill(skill_name: str) -> BaseSkill | None:
    """根据 skill_name 获取大 Skill。"""
    return _combined_skill_registry().get(str(skill_name))


def _ensure_config_dir() -> None:
    SKILLS_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)


def _build_default_config() -> dict[str, Any]:
    combined = _combined_skill_registry()
    return {
        "skills": {
            skill_name: {
                "enabled": bool(skill.enabled),
                "actions": {
                    str(action.get("name")): bool(action.get("enabled", True))
                    for action in skill.get_actions()
                    if action.get("name")
                },
            }
            for skill_name, skill in combined.items()
        }
    }


def _write_config(config: dict[str, Any]) -> None:
    _ensure_config_dir()
    SKILLS_CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def _backup_broken_config() -> None:
    if not SKILLS_CONFIG_PATH.exists():
        return
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = SKILLS_CONFIG_PATH.with_name(f"skills_config.broken_{timestamp}.json")
    backup_path.write_bytes(SKILLS_CONFIG_PATH.read_bytes())


def _normalize_config(raw_config: dict[str, Any]) -> dict[str, Any]:
    default_config = _build_default_config()
    merged = deepcopy(default_config)
    raw_skills = dict(raw_config.get("skills") or {})

    for skill_name, skill_defaults in merged["skills"].items():
        raw_skill = dict(raw_skills.get(skill_name) or {})
        if isinstance(raw_skill.get("enabled"), bool):
            skill_defaults["enabled"] = raw_skill["enabled"]
        raw_actions = dict(raw_skill.get("actions") or {})
        for action_name in list(skill_defaults["actions"].keys()):
            if isinstance(raw_actions.get(action_name), bool):
                skill_defaults["actions"][action_name] = raw_actions[action_name]
    return merged


def _load_skills_config() -> tuple[dict[str, Any], str | None]:
    default_config = _build_default_config()
    _ensure_config_dir()

    if not SKILLS_CONFIG_PATH.exists():
        _write_config(default_config)
        return default_config, None

    try:
        raw_text = SKILLS_CONFIG_PATH.read_text(encoding="utf-8")
        raw_config = json.loads(raw_text)
        if not isinstance(raw_config, dict):
            raise ValueError("skills_config.json 顶层必须是对象。")
        merged = _normalize_config(raw_config)
        if merged != raw_config:
            _write_config(merged)
        return merged, None
    except Exception as exc:
        _backup_broken_config()
        _write_config(default_config)
        return default_config, f"技能配置损坏，已自动回退默认配置：{exc}"


def _get_skill_enabled(skill_name: str, config: dict[str, Any] | None = None) -> bool:
    config = config or _load_skills_config()[0]
    return bool(((config.get("skills") or {}).get(skill_name) or {}).get("enabled", True))


def _get_action_enabled(skill_name: str, action_name: str, config: dict[str, Any] | None = None) -> bool:
    config = config or _load_skills_config()[0]
    actions = (((config.get("skills") or {}).get(skill_name) or {}).get("actions") or {})
    return bool(actions.get(action_name, True))


def _merge_skill_metadata(skill: BaseSkill, config: dict[str, Any]) -> dict[str, Any]:
    payload = skill.metadata(include_actions=True)
    payload["source"] = "builtin"
    payload["enabled"] = _get_skill_enabled(skill.name, config=config)
    payload["actions"] = []

    for action in skill.get_actions():
        action_payload = deepcopy(action)
        action_payload["enabled"] = _get_action_enabled(skill.name, str(action.get("name") or ""), config=config)
        payload["actions"].append(action_payload)
    return payload


def list_skills(include_actions: bool = True) -> dict[str, Any]:
    """返回当前注册的大 Skill 元数据。"""
    try:
        config, config_error = _load_skills_config()
        skills = []
        combined = _combined_skill_registry()
        builtin_names = set(skill_registry.keys())
        for skill_name, skill in combined.items():
            payload = _merge_skill_metadata(skill, config)
            if skill_name not in builtin_names:
                payload["source"] = "uploaded"
            if not include_actions:
                payload.pop("actions", None)
            skills.append(payload)

        uploaded_skills = list_uploaded_skills()
        if not include_actions:
            for skill in uploaded_skills:
                skill.pop("actions", None)
        existing_uploaded = {str(skill.get("name")) for skill in skills if skill.get("source") == "uploaded"}
        skills.extend([skill for skill in uploaded_skills if str(skill.get("name")) not in existing_uploaded])

        result = {
            "total": len(skills),
            "enabled_count": sum(1 for skill in skills if skill.get("enabled")),
            "available_count": sum(1 for skill in skills if skill.get("available")),
            "skills": skills,
        }
        if config_error:
            result["error"] = config_error
        return result
    except Exception as exc:
        return {
            "total": 0,
            "enabled_count": 0,
            "available_count": 0,
            "skills": [],
            "error": f"Skill registry 初始化失败：{exc}",
        }


def get_action(skill_name: str, action_name: str) -> dict[str, Any] | None:
    """根据 skill 和 action 名称获取 action 元数据。"""
    skill = get_skill(skill_name)
    if skill is None:
        return None
    config, _ = _load_skills_config()
    for action in _merge_skill_metadata(skill, config).get("actions", []):
        if action.get("name") == action_name:
            return action
    return None


def set_skill_enabled(skill_name: str, enabled: bool) -> dict[str, Any]:
    """更新大 Skill 启用状态。"""
    skill = get_skill(skill_name)
    if skill is None:
        raise KeyError(f"未注册的 Skill: {skill_name}")

    config, _ = _load_skills_config()
    config.setdefault("skills", {}).setdefault(skill_name, {"enabled": True, "actions": {}})
    config["skills"][skill_name]["enabled"] = bool(enabled)
    _write_config(config)
    return {
        "success": True,
        "skill_name": skill_name,
        "enabled": bool(enabled),
        "message": "Skill 已启用" if enabled else "Skill 已禁用",
    }


def set_action_enabled(skill_name: str, action_name: str, enabled: bool) -> dict[str, Any]:
    """更新子 action 启用状态。"""
    skill = get_skill(skill_name)
    if skill is None:
        raise KeyError(f"未注册的 Skill: {skill_name}")

    target_action = None
    for action in skill.get_actions():
        if action.get("name") == action_name:
            target_action = action
            break
    if target_action is None:
        raise KeyError(f"Skill {skill_name} 下未找到 action: {action_name}")

    if bool(enabled) and (not bool(target_action.get("available", True)) or str(target_action.get("status") or "").lower() == "not_implemented"):
        raise ValueError(target_action.get("unavailable_reason") or "该子能力当前不可启用。")

    config, _ = _load_skills_config()
    config.setdefault("skills", {}).setdefault(skill_name, {"enabled": True, "actions": {}})
    config["skills"][skill_name].setdefault("actions", {})
    config["skills"][skill_name]["actions"][action_name] = bool(enabled)
    _write_config(config)
    return {
        "success": True,
        "skill_name": skill_name,
        "action_name": action_name,
        "enabled": bool(enabled),
        "message": "子能力已启用" if enabled else "子能力已禁用",
    }


def execute_skill(skill_name: str, action_name: str | None = None, **kwargs: Any) -> SkillResult:
    """执行某个大 Skill 或子 action。"""
    skill = get_skill(skill_name)
    if skill is None:
        return SkillResult(
            success=False,
            skill_name=str(skill_name),
            action_name=action_name,
            summary="未找到指定 Skill。",
            errors=[f"未注册的 Skill: {skill_name}"],
        )

    config, config_error = _load_skills_config()
    if config_error:
        kwargs.setdefault("warnings", []).append(config_error)

    if not _get_skill_enabled(skill.name, config=config):
        return SkillResult(
            success=False,
            skill_name=skill.name,
            action_name=action_name,
            summary="该能力已禁用或不可用。",
            errors=[f"Skill {skill.display_name} 当前已禁用。"],
        )

    if not skill.available:
        return SkillResult(
            success=False,
            skill_name=skill.name,
            action_name=action_name,
            summary="该能力已禁用或不可用。",
            errors=[skill.unavailable_reason or f"Skill {skill.display_name} 当前不可用。"],
        )

    if action_name:
        action_metadata = get_action(skill_name, action_name)
        if action_metadata is None:
            return SkillResult(
                success=False,
                skill_name=skill.name,
                action_name=action_name,
                summary="该能力已禁用或不可用。",
                errors=[f"未找到 action: {action_name}"],
            )
        if not bool(action_metadata.get("enabled", True)):
            return SkillResult(
                success=False,
                skill_name=skill.name,
                action_name=action_name,
                summary="该能力已禁用或不可用。",
                errors=[f"子能力 {action_metadata.get('display_name') or action_name} 当前已禁用。"],
            )
        if not bool(action_metadata.get("available", True)):
            return SkillResult(
                success=False,
                skill_name=skill.name,
                action_name=action_name,
                summary="该能力已禁用或不可用。",
                errors=[action_metadata.get("unavailable_reason") or f"子能力 {action_name} 当前不可用。"],
            )

    kwargs["action_enabled_map"] = dict((((config.get("skills") or {}).get(skill_name) or {}).get("actions") or {}))
    return skill.execute(action_name=action_name, **kwargs)


def _skill_list_provider() -> dict[str, Any]:
    """给 agent_system_skill 提供技能列表。"""
    return list_skills(include_actions=True)


def match_uploaded_skill(message: str) -> tuple[UploadedPackageSkill | None, dict[str, Any] | None]:
    """基于上传 Skill 的 metadata/SKILL.md 做语义匹配。"""
    best_skill: UploadedPackageSkill | None = None
    best_score = 0
    best_reason = ""
    for skill in discover_uploaded_package_skills(CUSTOM_SKILL_ROOT):
        score, reason = skill.score_message(message)
        if score > best_score:
            best_skill = skill
            best_score = score
            best_reason = reason
    if best_skill is None or best_score < 6:
        return None, None
    return best_skill, {"score": best_score, "reason": best_reason, "route": "uploaded_skill_match"}


register_skill(SpectralFileSkill())
register_skill(SpectralPreprocessingSkill())
register_skill(MethanolAnalysisSkill())
register_skill(SpectralVisualizationSkill())
register_skill(ExperimentReportSkill())
register_skill(AgentSystemSkill(skill_list_provider=_skill_list_provider))
