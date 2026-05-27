"""用户上传 Skill 包的发现、匹配与执行。"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
import time
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from backend.agent.session_store import get_last_analysis, get_recent_messages, get_task_state, get_session
from backend.services.llm_service import LLMService

from .base import BaseSkill, SkillResult


logger = logging.getLogger(__name__)
MAX_PROMPT_ONLY_SKILL_CONTEXT_CHARS = 16000
MAX_PROMPT_ONLY_DOCUMENT_EXCERPT_CHARS = 6000
SUPPORTED_INPUT_TO_SUFFIXES = {
    "txt": [".txt"],
    "text": [".txt"],
    "markdown": [".md", ".markdown"],
    "html": [".html", ".htm"],
    "json": [".json"],
    "env": [".env"],
    "ini": [".ini"],
    "cfg": [".cfg", ".conf"],
    "properties": [".properties"],
    "yaml": [".yaml", ".yml"],
    "xml": [".xml"],
    "csv": [".csv"],
    "tsv": [".tsv"],
    "xlsx": [".xlsx", ".xls"],
    "docx": [".docx"],
    "pdf": [".pdf"],
    "log": [".log"],
    "python": [".py"],
    "java": [".java"],
    "folder": [],
    "file": [],
    "zip": [".zip"],
    "tar": [".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz"],
}
TEXT_LIKE_SUFFIXES = {
    ".txt",
    ".md",
    ".markdown",
    ".py",
    ".java",
    ".js",
    ".ts",
    ".html",
    ".css",
    ".xml",
    ".json",
    ".yaml",
    ".yml",
    ".ini",
    ".toml",
    ".properties",
    ".log",
    ".sql",
    ".sh",
    ".docx",
    ".pdf",
}
TABULAR_SUFFIXES = {".csv", ".tsv", ".xlsx", ".xls"}
ARCHIVE_SUFFIXES = {".zip", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz"}
TEXT_ANALYSIS_STOPWORDS = {
    "的", "和", "是", "在", "了", "与", "及", "或", "也", "就", "都", "而", "但", "如果", "一个", "一些",
    "这个", "那个", "这些", "那些", "当前", "已经", "可以", "需要", "进行", "处理", "分析", "结果", "内容",
    "文件", "文本", "项目", "功能", "任务", "问题", "说明", "记录", "我们", "你们", "他们", "我", "你", "他",
    "this", "that", "these", "those", "the", "and", "or", "for", "with", "from", "into", "onto", "about",
    "file", "text", "data", "analysis", "result", "content", "task", "issue", "note", "notes", "report",
    "skill", "agent", "output", "input", "script", "run", "process",
}


def _normalize_text(text: str) -> str:
    return re.sub(r"[\s\-_.,:;!?，。；：！？/\\()（）]+", "", str(text or "").strip().lower())


def _extract_tokens(text: str) -> list[str]:
    raw_tokens = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", _normalize_text(text))
    return [token for token in raw_tokens if len(token) >= 2]


def _full_file_suffix(path: str | Path | None) -> str:
    suffixes = Path(path or "").suffixes
    if not suffixes:
        return ""
    return "".join(suffixes).lower()


def _supported_suffixes_from_manifest(manifest: dict[str, Any]) -> list[str]:
    explicit = [str(item).strip().lower() for item in (manifest.get("supported_file_types") or []) if str(item).strip()]
    derived: list[str] = []
    for item in manifest.get("supported_inputs") or []:
        derived.extend(SUPPORTED_INPUT_TO_SUFFIXES.get(str(item).strip().lower(), []))
    seen: set[str] = set()
    ordered: list[str] = []
    for item in [*explicit, *derived]:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _extract_yaml_frontmatter(text: str) -> dict[str, Any]:
    """从 SKILL.md 头部提取简化版 YAML frontmatter。"""
    raw = str(text or "")
    if not raw.startswith("---"):
        return {}

    lines = raw.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}

    frontmatter_lines: list[str] = []
    end_index = None
    for idx, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = idx
            break
        frontmatter_lines.append(line.rstrip("\n"))
    if end_index is None:
        return {}

    data: dict[str, Any] = {}
    current_list_key: str | None = None
    for raw_line in frontmatter_lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- ") and current_list_key:
            data.setdefault(current_list_key, [])
            if isinstance(data[current_list_key], list):
                data[current_list_key].append(stripped[2:].strip().strip("'\""))
            continue
        if ":" not in line:
            current_list_key = None
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            current_list_key = None
            continue
        if not value:
            data[key] = []
            current_list_key = key
            continue
        current_list_key = None
        lowered = value.lower()
        if lowered in {"true", "false"}:
            data[key] = lowered == "true"
        else:
            data[key] = value.strip().strip("'\"")
    return data


def _list_resource_files(package_dir: Path, folder_name: str, limit: int = 50) -> list[str]:
    """列出 Skill 包中指定资源目录下的文件。"""
    folder = Path(package_dir) / folder_name
    if not folder.exists() or not folder.is_dir():
        return []
    files: list[str] = []
    for path in sorted(folder.rglob("*")):
        if path.is_file():
            files.append(str(path.relative_to(package_dir)).replace("\\", "/"))
        if len(files) >= limit:
            break
    return files


def _read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        logger.exception("读取 Skill 文本文件失败: %s", path)
        return ""


def _extract_docx_text(path: Path) -> str:
    try:
        with zipfile.ZipFile(path, "r") as archive:
            xml_bytes = archive.read("word/document.xml")
    except Exception:
        logger.exception("读取 docx 正文失败: %s", path)
        return ""

    try:
        root = ET.fromstring(xml_bytes)
    except Exception:
        logger.exception("解析 docx XML 失败: %s", path)
        return ""

    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", namespace):
        fragments = [node.text or "" for node in paragraph.findall(".//w:t", namespace)]
        text = "".join(fragments).strip()
        if text:
            paragraphs.append(text)
    return "\n".join(paragraphs)


def _extract_prompt_only_file_excerpt(file_path: str | None) -> str:
    path = Path(str(file_path or "").strip())
    if not path.exists() or not path.is_file():
        return ""

    suffix = _full_file_suffix(path)
    text = ""
    if suffix in {".txt", ".md", ".markdown", ".json", ".yaml", ".yml", ".csv", ".tsv", ".html", ".htm", ".xml", ".log"}:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            logger.exception("读取提示词型 Skill 文件正文失败: %s", path)
            text = ""
    elif suffix == ".docx":
        text = _extract_docx_text(path)

    return _truncate_text(text.strip(), MAX_PROMPT_ONLY_DOCUMENT_EXCERPT_CHARS) if text.strip() else ""


def _folder_contains_files(folder: Path) -> bool:
    if not folder.exists() or not folder.is_dir():
        return False
    return any(item.is_file() for item in folder.rglob("*"))


def _has_manifest_entrypoint(manifest: dict[str, Any]) -> bool:
    if not isinstance(manifest, dict):
        return False
    direct_keys = ("entrypoint", "entrypoints", "default_entrypoint", "script", "script_path", "main")
    for key in direct_keys:
        value = manifest.get(key)
        if isinstance(value, str) and value.strip():
            return True
        if isinstance(value, dict) and any(str(item).strip() for item in value.values() if isinstance(item, str)):
            return True
        if isinstance(value, list) and any(str(item).strip() for item in value):
            return True
    return False


def _resolve_manifest_entrypoint(manifest: dict[str, Any]) -> str:
    if not isinstance(manifest, dict):
        return ""

    for key in ("default_entrypoint", "entrypoint", "script", "script_path", "main"):
        value = manifest.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    entrypoints = manifest.get("entrypoints")
    if isinstance(entrypoints, dict):
        for name, value in entrypoints.items():
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict):
                for nested_key in ("path", "script", "entrypoint"):
                    nested_value = value.get(nested_key)
                    if isinstance(nested_value, str) and nested_value.strip():
                        return nested_value.strip()
        if any(str(item).strip() for item in entrypoints.keys()):
            return "manifest.entrypoints"
    if isinstance(entrypoints, list):
        for item in entrypoints:
            if isinstance(item, str) and item.strip():
                return item.strip()
    return ""


def _inspect_package_structure(
    package_dir: Path,
    manifest: dict[str, Any],
    skill_md_text: str,
    metadata_source: str | None,
) -> dict[str, Any]:
    skill_md_path = Path(package_dir) / "SKILL.md"
    readme_path = Path(package_dir) / "README.md"
    scripts_dir = Path(package_dir) / "scripts"
    has_skill_md = skill_md_path.exists()
    has_manifest = str(metadata_source or "").strip() in {"manifest.json", "metadata.json"}
    has_scripts = _folder_contains_files(scripts_dir)
    manifest_entrypoint = _resolve_manifest_entrypoint(manifest)
    has_manifest_entrypoint = has_manifest and _has_manifest_entrypoint(manifest)
    has_executable_entrypoint = bool(manifest_entrypoint)

    if has_manifest_entrypoint or has_scripts:
        skill_mode = "executable"
    elif has_skill_md and not has_manifest and not has_scripts:
        skill_mode = "prompt_only"
    elif has_skill_md and (has_scripts or has_manifest_entrypoint):
        skill_mode = "executable"
    elif has_manifest and has_executable_entrypoint:
        skill_mode = "executable"
    elif not has_skill_md and not has_manifest:
        skill_mode = "invalid"
    elif has_skill_md:
        skill_mode = "prompt_only"
    else:
        skill_mode = "invalid"

    if skill_mode == "prompt_only" and not has_skill_md:
        skill_mode = "invalid"

    return {
        "has_skill_md": has_skill_md,
        "has_manifest": has_manifest,
        "has_scripts": has_scripts,
        "skill_mode": skill_mode,
        "entrypoint": manifest_entrypoint,
        "has_manifest_entrypoint": has_manifest_entrypoint,
        "has_readme": readme_path.exists(),
        "skill_md_text": skill_md_text if has_skill_md else "",
    }


def _truncate_text(text: str, limit: int = MAX_PROMPT_ONLY_SKILL_CONTEXT_CHARS) -> str:
    normalized = str(text or "")
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 24)] + "\n\n[内容已截断]"


def _normalize_frontmatter_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return []
        if "," in normalized:
            return [item.strip() for item in normalized.split(",") if item.strip()]
        return [normalized]
    return []


def _build_manifest_from_skill_md(package_dir: Path, skill_md: str) -> dict[str, Any]:
    """在没有 manifest/metadata 时，从 SKILL.md frontmatter 构造最小元数据。"""
    frontmatter = _extract_yaml_frontmatter(skill_md)
    inferred_name = str(frontmatter.get("name") or package_dir.name).strip() or package_dir.name
    inferred_description = str(frontmatter.get("description") or "用户上传 Skill").strip() or "用户上传 Skill"
    payload: dict[str, Any] = {
        "id": inferred_name,
        "name": inferred_name,
        "display_name": str(frontmatter.get("display_name") or inferred_name),
        "description": inferred_description,
        "version": str(frontmatter.get("version") or "uploaded"),
        "skill_file": "SKILL.md",
        "default_entrypoint": str(frontmatter.get("default_entrypoint") or "").strip(),
        "supported_inputs": _normalize_frontmatter_list(frontmatter.get("supported_inputs")),
        "capabilities": _normalize_frontmatter_list(frontmatter.get("capabilities")),
        "triggers": _normalize_frontmatter_list(frontmatter.get("triggers")),
    }
    return payload


def _read_package_metadata(package_dir: Path) -> tuple[dict[str, Any], str | None]:
    """优先读取 manifest.json，其次 metadata.json，最后回退到 SKILL.md frontmatter。"""
    package_dir = Path(package_dir)
    manifest_path = package_dir / "manifest.json"
    metadata_path = package_dir / "metadata.json"
    skill_md_path = package_dir / "SKILL.md"
    for candidate in (manifest_path, metadata_path):
        if candidate.exists():
            try:
                payload = json.loads(candidate.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    return payload, candidate.name
            except Exception:
                logger.exception("读取上传 Skill 元数据失败: %s", candidate)
    if skill_md_path.exists():
        try:
            skill_md = skill_md_path.read_text(encoding="utf-8")
            payload = _build_manifest_from_skill_md(package_dir, skill_md)
            if payload:
                return payload, "SKILL.md frontmatter"
        except Exception:
            logger.exception("从 SKILL.md frontmatter 构造上传 Skill 元数据失败: %s", skill_md_path)
    return {}, None


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


def _extract_text_keywords(text: str, limit: int = 5) -> list[str]:
    tokens = re.findall(r"[a-zA-Z_][a-zA-Z0-9_+-]{2,}|[\u4e00-\u9fff]{2,}", str(text or ""))
    counter: Counter[str] = Counter()
    for token in tokens:
        normalized = token.strip().lower()
        if not normalized or normalized in TEXT_ANALYSIS_STOPWORDS:
            continue
        if len(normalized) <= 1:
            continue
        counter[normalized] += 1
    return [token for token, _ in counter.most_common(limit)]


def _build_text_analysis_summary(text: str, file_path: str | None = None) -> tuple[str, list[str], list[str]]:
    normalized_text = str(text or "")
    lines = [line.strip() for line in normalized_text.splitlines() if line.strip()]
    keywords = _extract_text_keywords(normalized_text, limit=5)
    key_points: list[str] = []
    warnings: list[str] = []

    if lines:
        line_count = len(lines)
        summary_head = f"已完成文本分析，内容约 {line_count} 行"
    else:
        summary_head = "已完成文本分析，但文件正文较少"

    if keywords:
        summary = f"{summary_head}，主要涉及：{'、'.join(keywords)}。"
    else:
        summary = f"{summary_head}，未提取到明显主题关键词。"

    headline_candidates = []
    for line in lines:
        cleaned = re.sub(r"^[#\-*•\d\.\)\s]+", "", line).strip()
        if not cleaned:
            continue
        if len(cleaned) < 6:
            continue
        if "=" in cleaned and len(cleaned) > 20:
            continue
        headline_candidates.append(cleaned)
        if len(headline_candidates) >= 3:
            break
    if headline_candidates:
        key_points.extend(f"内容重点：{item}" for item in headline_candidates[:3])

    if any(re.search(pattern, normalized_text, flags=re.I) for pattern in ("API_KEY", "SECRET", "TOKEN", "PASSWORD", "PRIVATE_KEY", "ACCESS_KEY")):
        warnings.append("检测到疑似敏感字段名，建议确认是否需要脱敏后再展示。")
    if any("=" in line for line in lines[:50]):
        warnings.append("文本中包含较多键值对样式内容，可能是配置或日志片段。")
    if file_path:
        warnings.insert(0, f"已分析文件：{Path(file_path).name}")

    return summary, key_points, warnings


class UploadedPackageSkill(BaseSkill):
    """把上传 Skill 包映射为可执行的大 Skill。"""

    category = "用户上传"
    requires_file = False
    supported_file_types: list[str] = []

    def __init__(self, package_dir: Path, manifest: dict[str, Any], skill_md: str, metadata_source: str | None = None) -> None:
        self.package_dir = Path(package_dir)
        self.manifest = dict(manifest or {})
        self.metadata_source = metadata_source or ""
        self.skill_md = str(skill_md or "")
        structure = _inspect_package_structure(self.package_dir, self.manifest, self.skill_md, self.metadata_source)

        self.name = str(self.manifest.get("name") or self.package_dir.name)
        self.display_name = str(self.manifest.get("display_name") or self.manifest.get("name") or self.package_dir.name)
        self.version = str(self.manifest.get("version") or "uploaded")
        self.description = str(self.manifest.get("description") or "用户上传 Skill")
        self.skill_mode = str(structure.get("skill_mode") or "invalid")
        self.has_skill_md = bool(structure.get("has_skill_md"))
        self.has_manifest = bool(structure.get("has_manifest"))
        self.has_scripts = bool(structure.get("has_scripts"))
        self.entrypoint = str(structure.get("entrypoint") or "")
        self.has_manifest_entrypoint = bool(structure.get("has_manifest_entrypoint"))
        self.has_readme = bool(structure.get("has_readme"))
        self.usage = (
            "提示词型 Skill 通过 SKILL.md、README.md、references/ 和 assets/ 增强大模型回答。"
            if self.skill_mode == "prompt_only"
            else "该 Skill 由用户上传，会根据描述、触发语义和包内指令参与路由。"
        )
        self.available = self.skill_mode != "invalid"
        self.unavailable_reason = "" if self.available else "Skill 包缺少 SKILL.md 或 manifest.json，无法识别。"
        self.supported_file_types = _supported_suffixes_from_manifest(self.manifest)
        self.task_types = [str(item) for item in (self.manifest.get("task_types") or []) if str(item).strip()]
        self.actions = [
            {
                "name": "run_uploaded_skill",
                "display_name": "执行上传 Skill",
                "description": (
                    "读取上传 Skill 的说明与可选脚本，并返回真实执行结果。"
                    if self.skill_mode == "executable"
                    else "读取提示词型 Skill 的上下文，并让大模型基于规则生成回答。"
                ),
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

    def supports_file_suffix(self, suffix: str | None) -> bool:
        suffix = str(suffix or "").strip().lower()
        if not suffix:
            return False
        return suffix in {item.lower() for item in self.supported_file_types}

    def infer_task_type(self, message: str, file_suffix: str | None = None) -> str:
        text = _normalize_text(message)
        suffix = str(file_suffix or "").lower()
        if "rag" in text or "切块" in text or "分块" in text:
            return "rag_chunk"
        if "阅读理解" in text or "真题" in text or "考试" in text:
            return "exam_reading_extract"
        if "ppt" in text or "讲稿" in text:
            return "ppt_script"
        if "论文" in text or "精读" in text:
            return "paper_reading"
        if "翻译" in text or "对照" in text or "整理成markdown" in text:
            return "extract"
        if suffix in {".pdf", ".docx", ".pptx", ".txt", ".md"}:
            return "extract"
        return "extract"

    def metadata(self, include_actions: bool = True) -> dict[str, Any]:
        payload = super().metadata(include_actions=include_actions)
        payload["source"] = "uploaded"
        payload["skill_mode"] = self.skill_mode
        payload["has_skill_md"] = self.has_skill_md
        payload["has_manifest"] = self.has_manifest
        payload["has_scripts"] = self.has_scripts
        payload["entrypoint"] = self.entrypoint
        payload["has_manifest_entrypoint"] = self.has_manifest_entrypoint
        payload["triggers"] = list(self.triggers)
        payload["capabilities"] = list(self.capabilities)
        payload["expected_markers"] = list(self.expected_markers)
        payload["package_dir"] = str(self.package_dir)
        payload["metadata_source"] = self.metadata_source
        payload["task_types"] = list(self.task_types)
        payload["scripts"] = _list_resource_files(self.package_dir, "scripts")
        payload["references"] = _list_resource_files(self.package_dir, "references")
        payload["assets"] = _list_resource_files(self.package_dir, "assets")
        return payload

    def _collect_markdown_sections(self, folder_name: str, limit: int = 8) -> list[str]:
        folder = self.package_dir / folder_name
        if not folder.exists() or not folder.is_dir():
            return []
        sections: list[str] = []
        for path in sorted(folder.rglob("*.md")):
            if not path.is_file():
                continue
            relative_name = str(path.relative_to(self.package_dir)).replace("\\", "/")
            content = _read_text_file(path).strip()
            if not content:
                continue
            sections.append(f"### {relative_name}\n{content}")
            if len(sections) >= limit:
                break
        return sections

    def _build_prompt_only_skill_context(self) -> str:
        sections: list[str] = [
            f"# Skill: {self.display_name}",
            f"- skill_name: {self.name}",
            f"- skill_mode: {self.skill_mode}",
            f"- metadata_source: {self.metadata_source or 'unknown'}",
            f"- has_manifest: {self.has_manifest}",
            f"- has_skill_md: {self.has_skill_md}",
            f"- has_scripts: {self.has_scripts}",
            f"- entrypoint: {self.entrypoint or 'none'}",
        ]

        if self.skill_md.strip():
            sections.append("## SKILL.md\n" + self.skill_md.strip())

        readme_path = self.package_dir / "README.md"
        if readme_path.exists():
            readme_text = _read_text_file(readme_path).strip()
            if readme_text:
                sections.append("## README.md\n" + readme_text)

        reference_sections = self._collect_markdown_sections("references")
        if reference_sections:
            sections.append("## references/\n" + "\n\n".join(reference_sections))

        asset_sections = self._collect_markdown_sections("assets")
        if asset_sections:
            sections.append("## assets/\n" + "\n\n".join(asset_sections))

        return _truncate_text("\n\n".join(sections), MAX_PROMPT_ONLY_SKILL_CONTEXT_CHARS)

    def _build_conversation_context(self, session_id: str | None, user_message: str, file_path: str | None = None) -> dict[str, Any]:
        context: dict[str, Any] = {
            "session_id": session_id,
            "skill_name": self.name,
            "skill_display_name": self.display_name,
            "skill_mode": self.skill_mode,
            "user_message": user_message,
        }
        if file_path:
            context["file_name"] = Path(file_path).name
            context["file_path"] = file_path
            document_excerpt = _extract_prompt_only_file_excerpt(file_path)
            if document_excerpt:
                context["document_excerpt"] = document_excerpt
        if not session_id:
            return context

        session = get_session(session_id)
        if not session:
            return context

        recent_context: list[dict[str, str]] = []
        current_message = str(user_message or "").strip()
        for item in get_recent_messages(session_id, limit=6):
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip()
            content = str(item.get("content") or "").strip()
            if role == "user" and content == current_message:
                continue
            recent_context.append({"role": role, "content": content})
        if recent_context:
            context["recent_messages"] = recent_context

        last_analysis = get_last_analysis(session_id) or {}
        if isinstance(last_analysis, dict) and last_analysis:
            context["last_analysis"] = {
                "skill_name": last_analysis.get("skill_name"),
                "action_name": last_analysis.get("action_name"),
                "summary": last_analysis.get("llm_explanation") or last_analysis.get("reply") or last_analysis.get("message"),
                "saved_file": last_analysis.get("saved_file"),
            }

        task_state = get_task_state(session_id)
        if isinstance(task_state, dict) and task_state:
            context["task_state"] = task_state
        return context

    def _run_prompt_only_skill(
        self,
        *,
        user_message: str,
        session_id: str | None = None,
        file_path: str | None = None,
        conversation_context: dict[str, Any] | None = None,
    ) -> SkillResult:
        skill_context = self._build_prompt_only_skill_context()
        built_context = dict(conversation_context or self._build_conversation_context(session_id, user_message, file_path=file_path))

        llm_service = LLMService(conversation_id=session_id)
        llm_result = llm_service.generate_skill_augmented_reply(
            skill_context=skill_context,
            user_message=user_message,
            conversation_context=built_context,
        )
        reply = str(llm_result.get("reply") or "").strip()
        llm_success = bool(llm_result.get("success"))
        llm_error_message = str(llm_result.get("error_message") or "").strip()
        warnings = list(llm_result.get("warnings") or [])

        if not reply:
            reply = str(built_context.get("user_message") or user_message or "已根据提示词型 Skill 完成回答。").strip()
        if not llm_success and llm_error_message:
            warnings.append(llm_error_message)

        logger.info(
            "Prompt-only Skill executed: skill=%s skill_mode=%s llm_success=%s session_id=%s",
            self.name,
            self.skill_mode,
            llm_success,
            session_id or "",
        )

        return SkillResult(
            success=True,
            skill_name=self.name,
            action_name="run_uploaded_skill",
            summary=reply,
            data={
                "reply_text": reply,
                "skill_name": self.name,
                "skill_version": self.version,
                "skill_mode": self.skill_mode,
                "skill_instruction_loaded": True,
                "script_check": "not_applicable",
                "script_result": None,
                "file_reference_check": "not_applicable",
                "package_dir": str(self.package_dir),
                "source": "uploaded",
                "duration_ms": 0.0,
                "task_type": "prompt_only",
                "document_processor": False,
                "file_path": file_path or None,
                "analysis_summary": reply,
                "key_points": [],
                "warnings": warnings,
                "skill_context": skill_context,
                "conversation_context": built_context,
                "llm_success": llm_success,
                "llm_error_message": llm_error_message or None,
                "registered_resources": {
                    "scripts": _list_resource_files(self.package_dir, "scripts"),
                    "references": _list_resource_files(self.package_dir, "references"),
                    "assets": _list_resource_files(self.package_dir, "assets"),
                },
            },
            errors=[],
        )

    def _build_document_intelligence_reply(
        self,
        report_payload: dict[str, Any],
        file_path: str | None = None,
    ) -> tuple[str, list[str], list[str]]:
        """优先使用文档 Skill 生成的 JSON 报告构造更自然的分析结论。"""
        metadata = dict(report_payload.get("metadata") or {})
        document_type = str(report_payload.get("document_type") or "document").strip()
        summaries = [str(item).strip() for item in (report_payload.get("summary") or []) if str(item).strip()]
        action_items = [str(item).strip() for item in (report_payload.get("action_items") or []) if str(item).strip()]
        findings = [dict(item) for item in (report_payload.get("findings") or []) if isinstance(item, dict)]
        entities = dict(report_payload.get("entities") or {})

        summary_parts = []
        if metadata.get("line_count"):
            summary_parts.append(f"共约 {metadata.get('line_count')} 行")
        elif metadata.get("char_count"):
            summary_parts.append(f"共约 {metadata.get('char_count')} 个字符")
        detail_prefix = f"已完成文档分析，文档类型为 {document_type}"
        if summary_parts:
            detail_prefix += f"，{summary_parts[0]}"
        if summaries:
            detail_prefix += f"。核心内容包括：{'；'.join(summaries[:3])}"
        else:
            detail_prefix += "。"

        key_points: list[str] = []
        if action_items:
            key_points.extend(f"待处理事项：{item}" for item in action_items[:2])
        variable_fields = [str(item).strip() for item in (entities.get("variables_or_fields") or []) if str(item).strip()]
        if variable_fields:
            key_points.append("识别到的字段：" + "、".join(variable_fields[:6]))
        evidence = [str(item).strip() for item in (report_payload.get("evidence_snippets") or []) if str(item).strip()]
        if evidence and not key_points:
            key_points.extend(f"证据片段：{item}" for item in evidence[:2])

        warnings: list[str] = []
        if file_path:
            warnings.append(f"已分析文件：{Path(file_path).name}")
        for finding in findings[:3]:
            severity = str(finding.get("severity") or "info").strip().lower()
            message = str(finding.get("message") or "").strip()
            if message and severity in {"high", "warning"}:
                warnings.append(message)
        return detail_prefix, key_points, warnings

    def score_message(self, message: str, *, file_suffix: str | None = None) -> tuple[int, str]:
        normalized_message = _normalize_text(message)
        if not normalized_message:
            normalized_message = ""

        score = 0
        reasons: list[str] = []
        if self.supports_file_suffix(file_suffix):
            score += 18
            reasons.append(f"file_type:{file_suffix}")
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

        skill_text = self.skill_md
        if self.skill_mode == "prompt_only":
            skill_text = self._build_prompt_only_skill_context()
            keyword_context = _normalize_text(skill_text)
            keyword_message = _normalize_text(message)
            prompt_keywords = ("翻译", "总结", "摘要", "对照", "提炼", "整理", "markdown", "md", "文档", "文本", "报告")
            for keyword in prompt_keywords:
                if keyword in keyword_message and keyword in keyword_context:
                    score += 8
                    reasons.append(f"prompt_keyword:{keyword}")
        skill_tokens = _extract_tokens(skill_text)
        md_score = _score_message_against_tokens(message, skill_tokens[:80])
        if md_score > 0:
            score += min(md_score, 8)
            reasons.append("skill_md_overlap")

        return score, ",".join(reasons) or "no_match"

    def _run_document_processor(self, file_path: str, message: str, task_type: str) -> tuple[str, dict[str, Any] | None]:
        script_path = self.package_dir / "scripts" / "document_processor.py"
        if not script_path.exists():
            return "not_available", None

        input_path = Path(file_path)
        output_dir = self.package_dir / "outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        suffix = ".jsonl" if task_type == "rag_chunk" else ".md"
        output_path = output_dir / f"{input_path.stem}_{task_type}{suffix}"

        started = time.perf_counter()
        try:
            process = subprocess.run(
                [
                    sys.executable,
                    str(script_path),
                    str(input_path),
                    "--task",
                    task_type,
                    "--output",
                    str(output_path),
                ],
                cwd=str(self.package_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                check=False,
            )
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            stdout = (process.stdout or "").strip()
            stderr = (process.stderr or "").strip()
            if process.returncode != 0:
                logger.warning("文档处理脚本执行失败: %s, stderr=%s", script_path, stderr)
                return "failed", {
                    "returncode": process.returncode,
                    "stdout": stdout,
                    "stderr": stderr,
                    "duration_ms": duration_ms,
                    "output_path": str(output_path),
                }

            preview = ""
            if output_path.exists() and output_path.suffix.lower() == ".md":
                try:
                    preview = output_path.read_text(encoding="utf-8")[:2000]
                except Exception:
                    preview = ""

            return "passed", {
                "returncode": process.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "duration_ms": duration_ms,
                "output_path": str(output_path),
                "output_exists": output_path.exists(),
                "output_preview": preview,
                "task_type": task_type,
            }
        except Exception as exc:
            logger.exception("文档处理脚本执行异常: %s", script_path)
            return "failed", {"error": str(exc), "task_type": task_type, "output_path": str(output_path)}

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
                errors="replace",
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

    def _run_manifest_entrypoint(self, file_path: str, task_type: str) -> tuple[str, dict[str, Any] | None]:
        entrypoints = self.manifest.get("entrypoints") or {}
        if not isinstance(entrypoints, dict):
            return "not_available", None

        input_path = Path(file_path)
        suffix = _full_file_suffix(file_path)
        selected_name = ""
        output_path: Path | None = None
        json_path: Path | None = None
        command: list[str] | None = None

        task_routing = self.manifest.get("task_routing") or {}
        if isinstance(task_routing, dict):
            selected_name = str(task_routing.get(task_type) or task_routing.get("default") or "").strip()
        if not selected_name:
            default_entrypoint = str(self.manifest.get("default_entrypoint") or "").strip()
            if default_entrypoint:
                selected_name = default_entrypoint

        if suffix in TABULAR_SUFFIXES and entrypoints.get("table_profile"):
            selected_name = "table_profile"
            script_path = self.package_dir / str(entrypoints["table_profile"])
            output_path = self.package_dir / "reports" / f"{input_path.stem}_table_profile.md"
            json_path = self.package_dir / "reports" / f"{input_path.stem}_table_profile.json"
            command = [sys.executable, str(script_path), str(input_path), "--output", str(output_path), "--json", str(json_path)]
        elif suffix in TABULAR_SUFFIXES and entrypoints.get("tabular_profile"):
            selected_name = "tabular_profile"
            script_path = self.package_dir / str(entrypoints["tabular_profile"])
            output_path = self.package_dir / "reports" / f"{input_path.stem}_table_profile.md"
            command = [sys.executable, str(script_path), str(input_path), "--output", str(output_path)]
        elif suffix in ARCHIVE_SUFFIXES and entrypoints.get("archive_inspect"):
            selected_name = "archive_inspect"
            script_path = self.package_dir / str(entrypoints["archive_inspect"])
            output_path = self.package_dir / "reports" / f"{input_path.stem}_archive_contents.md"
            command = [sys.executable, str(script_path), str(input_path), "--output", str(output_path)]
        elif suffix in TEXT_LIKE_SUFFIXES and entrypoints.get("text_extract"):
            selected_name = "text_extract"
            script_path = self.package_dir / str(entrypoints["text_extract"])
            output_path = self.package_dir / "outputs" / f"{input_path.stem}_extracted_text.txt"
            command = [sys.executable, str(script_path), str(input_path), "--output", str(output_path)]
        elif selected_name and entrypoints.get(selected_name):
            script_path = self.package_dir / str(entrypoints[selected_name])
            if selected_name == "document_analyze":
                output_path = self.package_dir / "reports" / f"{input_path.stem}_document_analysis.md"
                json_path = self.package_dir / "reports" / f"{input_path.stem}_document_analysis.json"
                command = [sys.executable, str(script_path), str(input_path), "--output", str(output_path), "--json", str(json_path), "--mode", task_type if task_type in {"summary", "review", "extract"} else "auto"]
            elif selected_name == "batch_process":
                output_path = self.package_dir / "reports" / "document_batch" / "index.md"
                command = [sys.executable, str(script_path), str(input_path), "--output-dir", str(output_path.parent)]
            elif selected_name == "redact_document":
                output_path = self.package_dir / "outputs" / f"{input_path.stem}_redacted.txt"
                command = [sys.executable, str(script_path), str(input_path), "--output", str(output_path)]
            elif selected_name == "convert_document":
                output_path = self.package_dir / "outputs" / f"{input_path.stem}_converted.md"
                command = [sys.executable, str(script_path), str(input_path), "--format", "markdown", "--output", str(output_path)]
            else:
                output_path = self.package_dir / "reports" / f"{input_path.stem}_{selected_name}.md"
                command = [sys.executable, str(script_path), str(input_path), "--output", str(output_path)]
        elif entrypoints.get("inventory"):
            selected_name = "inventory"
            script_path = self.package_dir / str(entrypoints["inventory"])
            output_path = self.package_dir / "reports" / f"{input_path.stem}_inventory.md"
            json_path = self.package_dir / "reports" / f"{input_path.stem}_inventory.json"
            command = [sys.executable, str(script_path), str(input_path), "--output", str(output_path), "--json", str(json_path)]

        if not command or not output_path:
            return "not_available", None
        if not Path(command[1]).exists():
            return "not_available", {"selected_entrypoint": selected_name, "missing_script": command[1], "task_type": task_type}

        output_path.parent.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()
        try:
            process = subprocess.run(
                command,
                cwd=str(self.package_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                check=False,
            )
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            stdout = (process.stdout or "").strip()
            stderr = (process.stderr or "").strip()
            if process.returncode != 0:
                return "failed", {
                    "selected_entrypoint": selected_name,
                    "returncode": process.returncode,
                    "stdout": stdout,
                    "stderr": stderr,
                    "duration_ms": duration_ms,
                    "output_path": str(output_path),
                    "task_type": task_type,
                }

            preview = ""
            if output_path.exists():
                try:
                    preview = output_path.read_text(encoding="utf-8", errors="ignore")[:2000]
                except Exception:
                    preview = ""
            stdout_payload: dict[str, Any] | None = None
            if stdout:
                try:
                    stdout_payload = json.loads(stdout)
                except Exception:
                    stdout_payload = None
            if not preview and stdout_payload:
                preview = str(
                    stdout_payload.get("summary_preview")
                    or stdout_payload.get("message")
                    or ""
                )[:2000]
            return "passed", {
                "selected_entrypoint": selected_name,
                "returncode": process.returncode,
                "stdout": stdout,
                "stdout_payload": stdout_payload,
                "stderr": stderr,
                "duration_ms": duration_ms,
                "output_path": str(output_path),
                "json_path": str(json_path) if json_path else None,
                "output_exists": output_path.exists(),
                "output_preview": preview,
                "task_type": task_type,
            }
        except Exception as exc:
            logger.exception("上传 Skill entrypoint 执行异常: %s", selected_name)
            return "failed", {"selected_entrypoint": selected_name, "error": str(exc), "task_type": task_type, "output_path": str(output_path)}

    def run(self, **kwargs: Any) -> SkillResult:
        action_name = str(kwargs.get("action_name") or "run_uploaded_skill")
        message = str(kwargs.get("message") or kwargs.get("original_message") or "").strip()
        file_path = str(kwargs.get("file_path") or "").strip()
        file_suffix = _full_file_suffix(file_path) if file_path else ""
        task_type = str(kwargs.get("task_type") or "").strip() or self.infer_task_type(message, file_suffix=file_suffix)
        started = time.perf_counter()

        instruction_loaded = bool(self.skill_md.strip())
        runner_name = "using_prompt_only_runner" if self.skill_mode == "prompt_only" else "using_executable_runner"
        logger.info(
            "Uploaded Skill dispatch: skill=%s skill_mode=%s %s has_manifest=%s has_skill_md=%s has_scripts=%s entrypoint=%s file_path=%s",
            self.name,
            self.skill_mode,
            runner_name,
            self.has_manifest,
            self.has_skill_md,
            self.has_scripts,
            self.entrypoint or "",
            file_path or "",
        )
        if self.skill_mode == "prompt_only":
            prompt_only_result = self._run_prompt_only_skill(
                user_message=message,
                session_id=str(kwargs.get("session_id") or "").strip() or None,
                file_path=file_path or None,
                conversation_context=kwargs.get("conversation_context") if isinstance(kwargs.get("conversation_context"), dict) else None,
            )
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            prompt_only_result.data["duration_ms"] = duration_ms
            prompt_only_result.data["skill_mode"] = self.skill_mode
            prompt_only_result.data["skill_instruction_loaded"] = instruction_loaded
            prompt_only_result.data["task_type"] = "prompt_only"
            prompt_only_result.data["file_path"] = file_path or None
            logger.info(
                "Prompt-only Skill result ready: skill=%s success=%s elapsed_ms=%.2f",
                self.name,
                prompt_only_result.success,
                duration_ms,
            )
            return prompt_only_result

        if self.skill_mode == "invalid":
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.warning("Invalid uploaded Skill execution blocked: skill=%s", self.name)
            return SkillResult(
                success=False,
                skill_name=self.name,
                action_name=action_name,
                summary="Skill 包缺少有效的 SKILL.md 或 manifest.json。",
                data={
                    "reply_text": "Skill 包缺少有效的 SKILL.md 或 manifest.json。",
                    "skill_name": self.name,
                    "skill_version": self.version,
                    "skill_mode": self.skill_mode,
                    "skill_instruction_loaded": instruction_loaded,
                    "script_check": "invalid",
                    "script_result": None,
                    "file_reference_check": "failed",
                    "package_dir": str(self.package_dir),
                    "source": "uploaded",
                    "duration_ms": duration_ms,
                    "task_type": task_type,
                    "document_processor": False,
                    "file_path": file_path or None,
                    "analysis_summary": "Skill 包缺少有效的 SKILL.md 或 manifest.json。",
                    "key_points": [],
                    "warnings": [],
                    "registered_resources": {
                        "scripts": _list_resource_files(self.package_dir, "scripts"),
                        "references": _list_resource_files(self.package_dir, "references"),
                        "assets": _list_resource_files(self.package_dir, "assets"),
                    },
                },
                errors=["Skill 包缺少有效的 SKILL.md 或 manifest.json。"],
            )

        primary_marker = self.expected_markers[0] if self.expected_markers else "SKILL_UPLOAD_TEST_OK_v1"
        script_check = "not_available"
        script_result: dict[str, Any] | None = None
        document_processor = self.package_dir / "scripts" / "document_processor.py"
        if file_path and document_processor.exists():
            script_check, script_result = self._run_document_processor(file_path=file_path, message=message, task_type=task_type)
            primary_marker = self.expected_markers[0] if self.expected_markers else "DOCUMENT_PROCESS_OK_v1"
        elif file_path:
            script_check, script_result = self._run_manifest_entrypoint(file_path=file_path, task_type=task_type)
            if script_check == "passed":
                primary_marker = self.expected_markers[0] if self.expected_markers else "DOCUMENT_PROCESS_OK_v1"
        elif self.package_dir.joinpath("scripts", "skill_test.py").exists():
            script_check, script_result = self._run_packaged_script(message)

        analysis_summary, key_points, warnings = "已完成分析。", [], []
        if script_result:
            stdout_payload = script_result.get("stdout_payload") if isinstance(script_result, dict) else None
            json_path = str(script_result.get("json_path") or "").strip() if isinstance(script_result, dict) else ""
            if (
                isinstance(stdout_payload, dict)
                and str(stdout_payload.get("selected_entrypoint") or "") == "document_analyze"
                and json_path
                and Path(json_path).exists()
            ):
                try:
                    report_payload = json.loads(Path(json_path).read_text(encoding="utf-8"))
                    analysis_summary, key_points, warnings = self._build_document_intelligence_reply(
                        report_payload,
                        file_path=file_path,
                    )
                except Exception:
                    logger.exception("读取文档智能分析 JSON 报告失败: %s", json_path)
            if analysis_summary == "已完成分析。":
                analysis_summary, key_points, warnings = _build_text_analysis_summary(
                    script_result.get("output_preview") or script_result.get("stdout") or "",
                    file_path=file_path,
                )
        lines = [f"文件分析结论：{analysis_summary}"]
        if key_points:
            lines.extend(["", "关键点："] + [f"- {item}" for item in key_points])
        if warnings:
            lines.extend(["", "提示："] + [f"- {item}" for item in warnings])

        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        success = instruction_loaded and action_name == "run_uploaded_skill"
        if file_path:
            success = success and script_check == "passed"
        return SkillResult(
            success=success,
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
                "task_type": task_type,
                "document_processor": bool(document_processor.exists()),
                "file_path": file_path or None,
                "analysis_summary": analysis_summary,
                "key_points": key_points,
                "warnings": warnings,
                "registered_resources": {
                    "scripts": _list_resource_files(self.package_dir, "scripts"),
                    "references": _list_resource_files(self.package_dir, "references"),
                    "assets": _list_resource_files(self.package_dir, "assets"),
                },
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
    candidate_dirs: list[Path] = []
    for manifest_path in root.rglob("manifest.json"):
        candidate_dirs.append(manifest_path.parent)
    for metadata_path in root.rglob("metadata.json"):
        candidate_dirs.append(metadata_path.parent)
    for skill_md_path in root.rglob("SKILL.md"):
        candidate_dirs.append(skill_md_path.parent)

    for package_dir in candidate_dirs:
        if package_dir in seen:
            continue
        skill_md_path = package_dir / "SKILL.md"
        manifest_path = package_dir / "manifest.json"
        metadata_path = package_dir / "metadata.json"
        if not skill_md_path.exists() and not manifest_path.exists() and not metadata_path.exists():
            continue
        manifest, metadata_source = _read_package_metadata(package_dir)
        try:
            skill_md = skill_md_path.read_text(encoding="utf-8") if skill_md_path.exists() else ""
        except Exception:
            logger.exception("读取上传 Skill SKILL.md 失败: %s", skill_md_path)
            continue
        seen.add(package_dir)
        skill = UploadedPackageSkill(package_dir=package_dir, manifest=manifest, skill_md=skill_md, metadata_source=metadata_source)
        if skill.skill_mode == "invalid":
            logger.info(
                "Skipping invalid uploaded Skill package: package_dir=%s has_skill_md=%s has_manifest=%s has_scripts=%s entrypoint=%s",
                package_dir,
                skill.has_skill_md,
                skill.has_manifest,
                skill.has_scripts,
                skill.entrypoint,
            )
            continue
        skills.append(skill)
    return skills
