"""静态文件与报告下载接口。"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from raman_core.methanol.config import REPORT_DIR, ensure_dirs


router = APIRouter(prefix="/api/files", tags=["files"])


def validate_report_file_name(report_file: str) -> str:
    """校验报告文件名，防止路径穿越。"""
    if not report_file:
        raise ValueError("报告文件名不能为空。")
    if any(token in report_file for token in ("..", "/", "\\")):
        raise ValueError("报告文件名不合法。")

    safe_name = Path(report_file).name
    if safe_name != report_file:
        raise ValueError("报告文件名不合法。")
    return safe_name


@router.get("/reports/{report_file}/download")
def download_report(report_file: str):
    """下载 Markdown 报告文件。"""
    ensure_dirs()
    try:
        safe_name = validate_report_file_name(report_file)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    path = REPORT_DIR / safe_name
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"报告文件不存在: {safe_name}")

    return FileResponse(
        path=path,
        media_type="text/markdown; charset=utf-8",
        filename=safe_name,
    )
