from __future__ import annotations

from backend.agent.agent_router import router as agent_router
from backend.main import app


def test_agent_router_keeps_only_tool_endpoint_after_stage3_split() -> None:
    paths = {route.path for route in agent_router.routes}

    assert paths == {"/api/agent/tools"}


def test_stage3_split_routes_are_registered_once() -> None:
    routes = {
        (method, getattr(route, "path", ""))
        for route in app.routes
        for method in (getattr(route, "methods", None) or [])
        if method not in {"HEAD", "OPTIONS"}
    }

    assert ("POST", "/api/agent/analyze-file") in routes
    assert ("POST", "/api/files/analyze") in routes
    assert ("GET", "/api/agent/skills") in routes
    assert ("GET", "/api/skills") in routes
