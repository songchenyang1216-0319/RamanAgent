"""Pydantic schemas for Raman pipeline requests and results."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PipelineStep(BaseModel):
    step_id: str | None = None
    algorithm_id: str
    params: dict[str, Any] = Field(default_factory=dict)
    display_name: str | None = None


class PipelineRequest(BaseModel):
    file_path: str | None = None
    template_id: str | None = None
    steps: list[PipelineStep] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)
    sample_name: str | None = None
    save_history: bool = True


class PipelineStepResult(BaseModel):
    step_id: str
    algorithm_id: str
    display_name: str
    status: str
    params: dict[str, Any] = Field(default_factory=dict)
    input_shape: dict[str, Any] = Field(default_factory=dict)
    output_shape: dict[str, Any] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    warning: str = ""
    error_message: str = ""
    elapsed_ms: int = 0


class PipelineResult(BaseModel):
    success: bool
    run_id: str
    template_id: str | None = None
    message: str
    steps: list[PipelineStepResult] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    final_spectrum: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    error_message: str = ""
    elapsed_ms: int = 0

