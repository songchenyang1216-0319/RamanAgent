from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException

from backend.db.session import get_engine
from backend.security.startup_checks import get_database_revision_status


router = APIRouter(tags=["health"])


def _database_status() -> dict:
    try:
        with get_engine().connect() as connection:
            connection.exec_driver_sql("SELECT 1")
        revision = get_database_revision_status()
        return {"ok": True, "revision": revision}
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__}


def _redis_status() -> dict:
    redis_url = os.getenv("REDIS_URL") or os.getenv("CELERY_BROKER_URL")
    if not redis_url:
        return {"ok": True, "enabled": False}
    try:
        import redis

        client = redis.Redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
        client.ping()
        return {"ok": True, "enabled": True}
    except Exception as exc:
        return {"ok": False, "enabled": True, "error": type(exc).__name__}


def _worker_status() -> dict:
    backend = str(os.getenv("TASK_QUEUE_BACKEND", "local") or "local").lower()
    if backend != "celery":
        return {"ok": True, "backend": backend}
    redis_state = _redis_status()
    return {"ok": bool(redis_state.get("ok")), "backend": backend, "redis": redis_state}


@router.get("/health/live")
def live() -> dict:
    return {"status": "ok"}


@router.get("/health/database")
def database() -> dict:
    status = _database_status()
    if not status.get("ok"):
        raise HTTPException(status_code=503, detail=status)
    return status


@router.get("/health/redis")
def redis_health() -> dict:
    status = _redis_status()
    if not status.get("ok"):
        raise HTTPException(status_code=503, detail=status)
    return status


@router.get("/health/worker")
def worker_health() -> dict:
    status = _worker_status()
    if not status.get("ok"):
        raise HTTPException(status_code=503, detail=status)
    return status


@router.get("/health/ready")
def ready() -> dict:
    database_status = _database_status()
    redis_status = _redis_status()
    worker_status = _worker_status()
    checks = {"database": database_status, "redis": redis_status, "worker": worker_status}
    app_env = str(os.getenv("APP_ENV", "development") or "development").lower()
    revision = database_status.get("revision") or {}
    revision_required = app_env in {"production", "prod", "staging"}
    ok = bool(database_status.get("ok")) and bool(worker_status.get("ok"))
    if str(os.getenv("TASK_QUEUE_BACKEND", "local")).lower() == "celery":
        ok = ok and bool(redis_status.get("ok"))
    if revision_required:
        ok = ok and bool(revision.get("ok"))
    if not ok:
        raise HTTPException(status_code=503, detail={"status": "not_ready", "checks": checks})
    return {"status": "ready", "checks": checks}
