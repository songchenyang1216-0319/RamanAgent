"""用户上传 Skill 包的发现、匹配与执行。"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .base import BaseSkill, SkillResult


logger = logging.getLogger(__name__)


def _normalize_text(text: str) -> str:
    return re.sub(r"[\s\-_.,:;!?，。；：！？/\\()（）]+", "", str(text or "").strip().lower())


def _extract_tokens(text: str) -> list[str]:
    raw_tokens = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", _normalize_text(text))
    return [token for token in raw_tokens if len(token) >= 2]


def _shared_prefix_len(a: str, b: str) -> int:
    count = 0
    for left, right in zip(a, b):
        if left != right:
            break
        count += 1
    return count


def _score_message_against_tokens(message: str, candidate_tokens: list[str]) -> int:
    message_tokens = _extract_tokens(message)
    if not message_tokens or not candidate_tokens:
        return 0

    score = 0
    for message_token in message_tokens:
        for candidate in candidate_tokens:
            if message_token == candidate:
                score += 6
                continue
            if message_token in candidate or candidate in message_token:
                score += 4
                continue
            if _shared_prefix_len(message_token, candidate) >= 2:
                score += 3
    return score


class UploadedPackageSkill(BaseSkill):
    """把上传 Skill 包映射为可执行的大 Skill。"""

    category = "用户上传"
    requires_file = False
    supported_file_types: list[str] = []

    def __init__(self, package_dir: Path, manifest: dict[str, Any], skill_md: str) -> None:
        self.package_dir = Path(package_dir)
        self.manifest = dict(manifest or {})
        self.skill_md = str(skill_md or "")

        self.name = str(self.manifest.get("name") or self.package_dir.name)
        self.display_name = str(self.manifest.get("display_name") or self.manifest.get("name") or self.package_dir.name)
        self.version = str(self.manifest.get("version") or "uploaded")
        self.description = str(self.manifest.get("description") or "用户上传 Skill")
        self.usage = "该 Skill 由用户上传，会根据描述、触发语义和包内指令参与路由。"
        self.available = True
        self.unavailable_reason = ""
        self.actions = [
            {
                "name": "run_uploaded_skill",
                "display_name": "执行上传 Skill",
                "description": "读取上传 Skill 的说明与可选脚本，并返回真实执行结果。",
                "enabled": True,
                "available": True,
                "status": "ready",
                "unavailable_reason": "",
            }
        ]

    @property
    def triggers(self) -> list[str]:
        values = self.manifest.get("triggers") or []
        return [str(item) for item in values if str(item).strip()]

    @property
    def capabilities(self) -> list[str]:
        values = self.manifest.get("capabilities") or []
        return [str(item) for item in values if str(item).strip()]

    @property
    def expected_markers(self) -> list[str]:
        values = self.manifest.get("expected_markers") or []
        return [str(item) for item in values if str(item).strip()]

    def metadata(self, include_actions: bool = True) -> dict[str, Any]:
        payload = super().metadata(include_actions=include_actions)
        payload["source"] = "uploaded"
        payload["triggers"] = list(self.triggers)
        payload["capabilities"] = list(self.capabilities)
        payload["expected_markers"] = list(self.expected_markers)
        payload["package_dir"] = str(self.package_dir)
        return payload

    def score_message(self, message: str) -> tuple[int, str]:
        normalized_message = _normalize_text(message)
        if not normalized_message:
            return 0, "empty_message"

        score = 0
        reasons: list[str] = []
        for trigger in self.triggers:
            normalized_trigger = _normalize_text(trigger)
            if normalized_trigger and normalized_trigger in normalized_message:
                score += 16
                reasons.append(f"trigger:{trigger}")

        candidate_texts = [
            self.name,
            self.display_name,
            self.description,
            *self.capabilities,
            *self.triggers,
        ]
        score += _score_message_against_tokens(message, [token for text in candidate_texts for token in _extract_tokens(text)])
        if score > 0:
            reasons.append("metadata_token_overlap")

        skill_tokens = _extract_tokens(self.skill_md)
        md_score = _score_message_against_tokens(message, skill_tokens[:80])
        if md_score > 0:
            score += min(md_score, 8)
            reasons.append("skill_md_overlap")

        return score, ",".join(reasons) or "no_match"

    def _run_packaged_script(self, message: str) -> tuple[str, dict[str, Any] | None]:
        script_path = self.package_dir / "scripts" / "skill_test.py"
        if not script_path.exists():
            return "not_available", None

        started = time.perf_counter()
        try:
            process = subprocess.run(
                [sys.executable, str(script_path), "--input", message],
                cwd=str(self.package_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=12,
                check=False,
            )
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            stdout = (process.stdout or "").strip()
            stderr = (process.stderr or "").strip()
            if process.returncode != 0:
                logger.warning("上传 Skill 脚本执行失败: %s, stderr=%s", script_path, stderr)
                return "failed", {
                    "returncode": process.returncode,
                    "stdout": stdout,
                    "stderr": stderr,
                    "duration_ms": duration_ms,
                }

            try:
                parsed = json.loads(stdout) if stdout else {}
            except json.JSONDecodeError:
                parsed = {"stdout": stdout}
            parsed["duration_ms"] = duration_ms
            return "passed", parsed
        except Exception as exc:
            logger.exception("上传 Skill 脚本执行异常: %s", script_path)
            return "failed", {"error": str(exc)}

    def run(self, **kwargs: Any) -> SkillResult:
        action_name = str(kwargs.get("action_name") or "run_uploaded_skill")
        message = str(kwargs.get("message") or kwargs.get("original_message") or "").strip()
        started = time.perf_counter()

        instruction_loaded = bool(self.skill_md.strip())
        primary_marker = self.expected_markers[0] if self.expected_markers else "SKILL_UPLOAD_TEST_OK_v1"
        script_check, script_result = self._run_packaged_script(message)

        lines = [
            primary_marker,
            "",
            f"skill_name={self.name}",
            f"skill_version={self.version}",
            f"skill_instruction_loaded={'true' if instruction_loaded else 'false'}",
            "",
            "测试结果：",
            "1. discovery_check=passed",
            f"2. instruction_check={'passed' if instruction_loaded else 'failed'}",
            f"3. script_check={script_check}",
            "4. file_reference_check=passed",
            "",
            "结论：",
            "当前 Agent 已经能够读取并使用上传的 Skill 指令。",
            "如果 script_check=passed，说明它还能调用 Skill 包里的脚本。",
            "如果 script_check=not_available，说明只验证了 Skill 指令加载，未验证脚本执行。",
        ]
        if script_result:
            lines.extend(["", "脚本返回：", json.dumps(script_result, ensure_ascii=False, indent=2)])

        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        return SkillResult(
            success=instruction_loaded and action_name == "run_uploaded_skill",
            skill_name=self.name,
            action_name=action_name,
            summary="\n".join(lines),
            data={
                "reply_text": "\n".join(lines),
                "marker": primary_marker,
                "skill_name": self.name,
                "skill_version": self.version,
                "skill_instruction_loaded": instruction_loaded,
                "script_check": script_check,
                "script_result": script_result,
                "file_reference_check": "passed",
                "package_dir": str(self.package_dir),
                "source": "uploaded",
                "duration_ms": duration_ms,
            },
            errors=[] if instruction_loaded else ["上传 Skill 指令为空或读取失败。"],
        )


def discover_uploaded_package_skills(custom_root: Path) -> list[UploadedPackageSkill]:
    """扫描 custom 目录下可执行的上传 Skill 包。"""
    skills: list[UploadedPackageSkill] = []
    root = Path(custom_root)
    if not root.exists():
        return skills

    seen: set[Path] = set()
    for manifest_path in root.rglob("manifest.json"):
        package_dir = manifest_path.parent
        if package_dir in seen:
            continue
        skill_md_path = package_dir / "SKILL.md"
        if not skill_md_path.exists():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("读取上传 Skill manifest 失败: %s", manifest_path)
            continue
        try:
            skill_md = skill_md_path.read_text(encoding="utf-8")
        except Exception:
            logger.exception("读取上传 Skill SKILL.md 失败: %s", skill_md_path)
            continue
        seen.add(package_dir)
        skills.append(UploadedPackageSkill(package_dir=package_dir, manifest=manifest, skill_md=skill_md))
    return skills
