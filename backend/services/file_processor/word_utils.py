from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from raman_core.methanol.config import PROJECT_ROOT


def convert_legacy_word_to_docx(path: str | Path) -> tuple[Path | None, str | None]:
    source_path = Path(path).resolve()
    if source_path.suffix.lower() != ".doc":
        return None, "仅支持旧版 .doc 文件转换。"

    temp_dir = PROJECT_ROOT / "storage" / "tmp" / "word-converted"
    temp_dir.mkdir(parents=True, exist_ok=True)
    target_path = temp_dir / f"{source_path.stem}_{source_path.stat().st_mtime_ns}.docx"
    if target_path.exists() and target_path.is_file():
        return target_path, None

    office_error = _try_libreoffice_convert(source_path, temp_dir, target_path)
    if target_path.exists() and target_path.is_file():
        return target_path, None

    word_error = _try_word_com_convert(source_path, target_path)
    if target_path.exists() and target_path.is_file():
        return target_path, None

    parts = [
        "当前环境无法解析旧版 .doc 文件。",
        "建议将文件另存为 .docx 后重试。",
    ]
    if office_error:
        parts.append(f"LibreOffice 转换失败：{office_error}")
    if word_error:
        parts.append(f"Word COM 转换失败：{word_error}")
    return None, " ".join(parts)


def extract_openxml_text(path: str | Path) -> tuple[str, int]:
    source_path = Path(path).resolve()
    try:
        with zipfile.ZipFile(source_path, "r") as archive:
            xml_bytes = archive.read("word/document.xml")
    except Exception as exc:
        raise RuntimeError(f"读取 OpenXML 正文失败：{exc}") from exc

    try:
        root = ET.fromstring(xml_bytes)
    except Exception as exc:
        raise RuntimeError(f"解析 OpenXML XML 失败：{exc}") from exc

    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", namespace):
        fragments = [node.text or "" for node in paragraph.findall(".//w:t", namespace)]
        text = "".join(fragments).strip()
        if text:
            paragraphs.append(text)
    return "\n".join(paragraphs), len(paragraphs)


def _try_libreoffice_convert(source_path: Path, temp_dir: Path, target_path: Path) -> str | None:
    soffice_path = shutil.which("soffice")
    if not soffice_path:
        possible_paths = [
            Path(os.environ.get("ProgramFiles", "")) / "LibreOffice" / "program" / "soffice.exe",
            Path(os.environ.get("ProgramFiles(x86)", "")) / "LibreOffice" / "program" / "soffice.exe",
        ]
        for candidate in possible_paths:
            if candidate.exists():
                soffice_path = str(candidate)
                break
    if not soffice_path:
        return "未找到 soffice。"

    try:
        completed = subprocess.run(
            [
                soffice_path,
                "--headless",
                "--convert-to",
                "docx",
                "--outdir",
                str(temp_dir),
                str(source_path),
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except Exception as exc:
        return str(exc)
    if completed.returncode != 0:
        stderr = (completed.stderr or completed.stdout or "").strip()
        return stderr or f"退出码 {completed.returncode}"
    return None


def _try_word_com_convert(source_path: Path, target_path: Path) -> str | None:
    if os.name != "nt":
        return "当前不是 Windows 环境。"

    script = "\n".join(
        [
            "param(",
            "  [string]$SourcePath,",
            "  [string]$TargetPath",
            ")",
            "$ErrorActionPreference = 'Stop'",
            "$source = [System.IO.Path]::GetFullPath($SourcePath)",
            "$target = [System.IO.Path]::GetFullPath($TargetPath)",
            "$word = $null",
            "$document = $null",
            "try {",
            "  $word = New-Object -ComObject Word.Application",
            "  $word.Visible = $false",
            "  $word.DisplayAlerts = 0",
            "  $document = $word.Documents.Open($source, $false, $true)",
            "  $document.SaveAs([ref]$target, [ref]16)",
            "} finally {",
            "  if ($document -ne $null) { $document.Close() }",
            "  if ($word -ne $null) { $word.Quit() }",
            "}",
        ]
    )

    script_path = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False, encoding="utf-8") as handle:
            handle.write(script)
            script_path = handle.name
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                script_path,
                "-SourcePath",
                str(source_path),
                "-TargetPath",
                str(target_path),
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except Exception as exc:
        return str(exc)
    finally:
        if script_path:
            try:
                Path(script_path).unlink(missing_ok=True)
            except Exception:
                pass
    if completed.returncode != 0:
        stderr = (completed.stderr or completed.stdout or "").strip()
        return stderr or f"退出码 {completed.returncode}"
    return None
