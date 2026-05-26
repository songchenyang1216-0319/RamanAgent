"""FastAPI 应用入口。"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.agent.agent_router import router as agent_router
from backend.api.file_api import router as file_router
from backend.api.history_api import router as history_router
from backend.api.methanol_api import router as methanol_router
from backend.model_registry.model_registry_router import router as model_registry_router
from backend.services.model_registry_service import ModelRegistryService
from backend.services.history_service import init_history_db
from raman_core.methanol.config import FIGURE_DIR, OUTPUT_DIR, PROJECT_ROOT, REPORT_DIR, ensure_dirs


ensure_dirs()


app = FastAPI(title="Multi-Skill Agent API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(agent_router)
app.include_router(methanol_router)
app.include_router(file_router)
app.include_router(history_router)
app.include_router(model_registry_router)
app.mount("/outputs", StaticFiles(directory=str(OUTPUT_DIR)), name="outputs")
app.mount("/static/figures", StaticFiles(directory=str(FIGURE_DIR)), name="static-figures")
app.mount("/static/reports", StaticFiles(directory=str(REPORT_DIR)), name="static-reports")
app.mount("/app", StaticFiles(directory=str(PROJECT_ROOT / "frontend"), html=True), name="frontend-app")


@app.on_event("startup")
def startup() -> None:
    """应用启动时初始化历史数据库。"""
    init_history_db()
    ModelRegistryService().load_registry()


@app.get("/")
def root() -> dict:
    """根接口，用于快速确认服务已启动。"""
    return {"message": "Multi-Skill Agent API is running"}


@app.get("/health")
def health() -> dict:
    """健康检查接口。"""
    return {"status": "ok"}
