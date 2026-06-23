from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FileAnalysisOptions(BaseModel):
    force: bool = False
    async_task: bool = False

    class Config:
        extra = "allow"


class FileAnalysisRequest(BaseModel):
    user_id: str | None = None
    conversation_id: str | None = None
    session_id: str | None = None
    file_id: str | None = None
    file_ids: list[str] = Field(default_factory=list)
    message: str | None = None
    skill_name: str | None = None
    action_name: str | None = None
    provider_id: str | None = None
    model_id: str | None = None
    options: FileAnalysisOptions = Field(default_factory=FileAnalysisOptions)
    metadata: dict[str, Any] = Field(default_factory=dict)
    debug: bool = False

    class Config:
        extra = "allow"


class FileAnalysisResult(BaseModel):
    success: bool
    reply: str | None = None
    message: str | None = None
    intent: str | None = None
    route: str | None = None
    skill_name: str | None = None
    action_name: str | None = None
    tool_name: str | None = None
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    files: list[dict[str, Any]] = Field(default_factory=list)
    file_id: str | None = None
    file_ids: list[str] = Field(default_factory=list)
    task_id: str | None = None
    conversation_id: str | None = None
    session_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    class Config:
        extra = "allow"


class FileAnalysisError(BaseModel):
    success: bool = False
    error_code: str
    error_message: str
    message: str
    suggestion: str = ""

    class Config:
        extra = "allow"
