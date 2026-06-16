"""FastAPI 应用入口。"""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.agent.agent_router import router as agent_router
from backend.api.auth_api import router as auth_router
from backend.api.conversation_api import router as conversation_router
from backend.api.file_api import router as file_router
from backend.api.knowledge_base_api import router as knowledge_base_router
from backend.api.llm_api import router as llm_router
from backend.api.memory_api import router as memory_router
from backend.api.model_api import router as model_router
from backend.api.project_api import router as project_router
from backend.api.rag_api import router as rag_router
from backend.api.raman_pipeline_api import router as raman_pipeline_router
from backend.api.report_api import router as report_router
from backend.api.skill_api import router as skill_router
from backend.api.workspace_api import router as workspace_router
from backend.api.history_api import router as history_router
from backend.api.methanol_api import router as methanol_router
from backend.services.user_service import UserService
from backend.model_registry.model_registry_router import router as model_registry_router
from backend.services.model_registry_service import ModelRegistryService
from backend.services.llm_registry_service import LLMRegistryService
from backend.db.database import init_agent_memory_db
from backend.services.history_service import init_history_db
from raman_core.methanol.config import FIGURE_DIR, OUTPUT_DIR, PROJECT_ROOT, REPORT_DIR, ensure_dirs


ensure_dirs()


app = FastAPI(title="RamanAgent API")
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
app.include_router(auth_router)
app.include_router(conversation_router)
app.include_router(methanol_router)
app.include_router(file_router)
app.include_router(knowledge_base_router)
app.include_router(memory_router)
app.include_router(model_router)
app.include_router(llm_router)
app.include_router(project_router)
app.include_router(rag_router)
app.include_router(raman_pipeline_router)
app.include_router(report_router)
app.include_router(skill_router)
app.include_router(workspace_router)
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
    init_agent_memory_db()
    ModelRegistryService().load_registry()
    LLMRegistryService().get_current_model()
    UserService().ensure_default_admin(app_env=str(os.getenv("APP_ENV", "development") or "development"))


@app.get("/")
def root() -> dict:
    """根接口，用于快速确认服务已启动。"""
    return {"message": "Multi-Skill Agent API is running"}


@app.get("/health")
def health() -> dict:
    """健康检查接口。"""
    return {"status": "ok"}
