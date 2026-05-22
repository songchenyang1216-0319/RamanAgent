"""甲醇预测相关 HTTP 接口。"""

from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from backend.agent.tools.spectral_tools.spectral_summary_tool import analyze_spectrum_professionally
from backend.schemas.methanol_schema import (
    ArtifactCheckItem,
    ArtifactCheckResponse,
    DemoPredictRequest,
    ExplainResultRequest,
    ExplainResultResponse,
)
from backend.services.history_service import save_analysis_history
from backend.services.llm_service import LLMService
from backend.services.model_registry_service import ModelRegistryService
from backend.services.report_service import generate_methanol_markdown_report
from backend.services.methanol_service import predict_methanol
from raman_core.methanol.config import ARTIFACT_DIR, DEMO_DATA_DIR, PROJECT_ROOT, RAW_DATA_DIR, ensure_dirs


router = APIRouter(prefix="/api/methanol", tags=["methanol"])

REQUIRED_ARTIFACTS = [
    "cdae_display_model.pt",
    "cdae_reg_model.pt",
    "caeplus_model.pt",
    "common_axis.npy",
    "latent_train.npy",
    "svr_model.pkl",
    "rf_model.pkl",
    "scaler.pkl",
    "config.json",
]


def sanitize_csv_filename(file_name: str) -> str:
    """清理上传文件名，避免路径穿越和危险字符。"""
    safe_name = Path(file_name or "").name
    if not safe_name:
        safe_name = "uploaded.csv"
    stem = Path(safe_name).stem
    stem = re.sub(r"[^0-9A-Za-z\u4e00-\u9fa5._-]+", "_", stem).strip("._-")
    if not stem:
        stem = "uploaded"
    return f"{stem}.csv"


def build_unique_raw_path(file_name: str) -> Path:
    """在 data/raw 下生成不会覆盖旧文件的唯一保存路径。"""
    ensure_dirs()
    safe_name = sanitize_csv_filename(file_name)
    target = RAW_DATA_DIR / safe_name
    if not target.exists():
        return target

    stem = target.stem
    suffix = target.suffix
    unique_name = f"{stem}_{uuid4().hex[:8]}{suffix}"
    return RAW_DATA_DIR / unique_name


async def save_uploaded_csv(file: UploadFile) -> Path:
    """复用上传保存逻辑，将 CSV 安全保存到 data/raw。"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="未提供上传文件名。")
    if Path(file.filename).suffix.lower() != ".csv":
        raise HTTPException(status_code=400, detail="只允许上传 .csv 文件。")

    save_path = build_unique_raw_path(file.filename)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="上传文件为空。")
    save_path.write_bytes(content)
    return save_path


def build_figure_web_urls(figures: dict) -> dict:
    """将本地图像路径转换为前端可访问的相对 URL。"""
    urls = {}
    for key, value in (figures or {}).items():
        file_name = Path(str(value)).name
        urls[key] = f"/static/figures/{file_name}" if file_name else ""
    return urls


def build_report_web_urls(report: dict) -> dict:
    """将报告信息转换为前端可访问的查看和下载 URL。"""
    report_file = str((report or {}).get("report_file", "") or "")
    report_markdown_file = str((report or {}).get("report_markdown_file", report_file) or "")
    report_html_file = str((report or {}).get("report_html_file", "") or "")
    return {
        "report_view": f"/static/reports/{report_html_file or report_markdown_file}" if (report_html_file or report_markdown_file) else "",
        "report_download": f"/api/files/reports/{report_markdown_file}/download" if report_markdown_file else "",
        "report_markdown_url": f"/static/reports/{report_markdown_file}" if report_markdown_file else "",
        "report_html_url": f"/static/reports/{report_html_file}" if report_html_file else "",
    }


@router.post("/predict")
async def predict(
    file: UploadFile = File(...),
    debug: bool = Query(default=False, description="是否返回 intermediate 中间光谱数组。"),
) -> dict:
    """接收上传的 CSV 文件，保存后执行甲醇预测。"""
    save_path = await save_uploaded_csv(file)

    try:
        result = predict_methanol(save_path, include_intermediate=debug)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "success": True,
        "saved_file": str(save_path.relative_to(PROJECT_ROOT)),
        "debug": debug,
        "result": result,
    }


@router.post("/explain-result", response_model=ExplainResultResponse)
def explain_result(request: ExplainResultRequest) -> ExplainResultResponse:
    """基于前端传来的公开预测结果生成中文解释。"""
    result = dict(request.result or {})
    result.pop("intermediate", None)

    llm_service = LLMService()
    explanation = llm_service.explain_methanol_result(result)
    if "未配置 SILICONFLOW_API_KEY" in explanation:
        return ExplainResultResponse(success=False, explanation=None, message=explanation)
    return ExplainResultResponse(success=True, explanation=explanation, message=None)


@router.get("/artifacts/check", response_model=ArtifactCheckResponse)
def check_artifacts() -> ArtifactCheckResponse:
    """检查推理所需 artifacts 是否齐全。"""
    service = ModelRegistryService()
    check_result = service.check_model_artifacts()
    if check_result.get("data"):
        data = check_result.get("data") or {}
        items = [
            ArtifactCheckItem(name=item["name"], exists=True, path=item.get("resolved_path", item["path"]))
            for item in data.get("existing_files", [])
        ]
        items.extend(
            ArtifactCheckItem(name=item["name"], exists=False, path=item["path"])
            for item in data.get("missing_files", [])
        )
        return ArtifactCheckResponse(
            overall=bool(check_result.get("success")),
            items=items,
        )

    items = []
    for name in REQUIRED_ARTIFACTS:
        path = ARTIFACT_DIR / name
        items.append(ArtifactCheckItem(name=name, exists=path.exists(), path=str(path.relative_to(PROJECT_ROOT)).replace("\\", "/")))

    return ArtifactCheckResponse(
        overall=all(item.exists for item in items),
        items=items,
    )


@router.get("/demo-files")
def list_demo_files() -> dict:
    """列出 data/demo 下可用的 CSV 文件。"""
    ensure_dirs()
    if not DEMO_DATA_DIR.exists():
        return {"files": []}
    files = sorted(path.name for path in DEMO_DATA_DIR.glob("*.csv"))
    return {"files": files}


@router.post("/predict-demo")
def predict_demo(
    request: DemoPredictRequest,
    debug: bool = Query(default=False, description="是否返回 intermediate 中间光谱数组。"),
) -> dict:
    """使用 data/demo 中的样例文件执行预测。"""
    ensure_dirs()
    target = DEMO_DATA_DIR / Path(request.file_name).name
    if target.suffix.lower() != ".csv":
        raise HTTPException(status_code=400, detail="demo 文件必须是 .csv。")
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"demo 文件不存在: {request.file_name}")

    try:
        result = predict_methanol(target, include_intermediate=debug)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "success": True,
        "saved_file": str(target.relative_to(PROJECT_ROOT)),
        "debug": debug,
        "result": result,
    }


@router.post("/predict-report")
async def predict_report(
    file: UploadFile = File(...),
    explain: bool = Query(default=True, description="是否调用大模型生成结果解释。"),
    debug: bool = Query(default=False, description="是否返回 intermediate 中间光谱数组。"),
) -> dict:
    """上传 CSV 后完成预测、解释和 Markdown 报告生成。"""
    save_path = await save_uploaded_csv(file)

    try:
        result = predict_methanol(save_path, include_intermediate=debug)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    llm_explanation = "未生成大模型解释"
    if explain:
        public_result = dict(result)
        public_result.pop("intermediate", None)
        llm_explanation = LLMService().explain_methanol_result(public_result)

    model_info = {}
    current_model_response = ModelRegistryService().get_current_model()
    if current_model_response.get("success"):
        model_info = dict(current_model_response.get("data") or {})

    professional_analysis = analyze_spectrum_professionally(save_path, result)
    result["professional_analysis"] = professional_analysis if professional_analysis.get("success") else {}
    result["model_info"] = model_info
    result["experiment_metadata"] = {}

    report = generate_methanol_markdown_report(result, llm_explanation)
    response_payload = {
        "success": True,
        "saved_file": str(save_path.relative_to(PROJECT_ROOT)),
        "debug": debug,
        "explain": explain,
        "result": result,
        "llm_explanation": llm_explanation,
        "report": report,
        "report_id": report.get("report_id"),
        "created_at": report.get("created_at"),
        "summary": report.get("summary"),
        "web_urls": {
            "figures": build_figure_web_urls(result.get("figures", {})),
            **build_report_web_urls(report),
        },
    }
    try:
        response_payload["history"] = save_analysis_history(response_payload)
    except Exception as exc:
        response_payload["history_error"] = str(exc)
    return response_payload
