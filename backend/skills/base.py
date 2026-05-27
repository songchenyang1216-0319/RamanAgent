"""Skill 基础类型定义。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class SkillResult:
    """统一的 Skill 返回结构。"""

    success: bool
    skill_name: str
    summary: str
    action_name: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    plots: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """转换成便于接口层直接返回的字典。"""
        return asdict(self)


class BaseSkill:
    """所有 Skill 的基础接口。"""

    name = "base_skill"
    display_name = "基础 Skill"
    description = "Base skill"
    category = "未分类"
    enabled = True
    available = True
    unavailable_reason = ""
    version = "v1"
    requires_file = False
    supported_file_types: list[str] = []
    usage = ""
    actions: list[dict[str, Any]] = []

    def metadata(self, include_actions: bool = True) -> dict[str, Any]:
        """返回 Skill 元数据。"""
        payload = {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "category": self.category,
            "enabled": bool(self.enabled),
            "available": bool(self.available),
            "unavailable_reason": self.unavailable_reason or "",
            "version": self.version,
            "requires_file": bool(self.requires_file),
            "supported_file_types": list(self.supported_file_types),
            "usage": self.usage or "",
        }
        if include_actions:
            payload["actions"] = self.get_actions()
        return payload

    def get_actions(self) -> list[dict[str, Any]]:
        """返回当前 Skill 可展示的子 action 列表。"""
        return deepcopy(list(self.actions))

    def run(self, **kwargs: Any) -> SkillResult:
        """执行 Skill。"""
        raise NotImplementedError

    def execute(self, action_name: str | None = None, **kwargs: Any) -> SkillResult:
        """执行 Skill 或其默认 action。"""
        clean_kwargs = dict(kwargs or {})
        clean_kwargs.pop("action_name", None)
        return self.run(action_name=action_name, **clean_kwargs)
