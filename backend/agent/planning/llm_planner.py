"""LLM planner with deterministic local fallback for tests and offline use."""

from __future__ import annotations

import json
import os
from typing import Any

from backend.agent.types import NormalizedMessage

from .plan_types import LLMPlan, PlannerOutput
from .json_repair import loads_json_with_repair
from .planner_config import PlannerConfig
from .rule_router import HighConfidenceRuleRouter
from .tool_catalog import ToolCatalog


class LLMPlanner:
    """Produce a strict JSON plan for the enhanced planning layer.

    The external LLM call is deliberately opt-in. In local development and tests,
    this class uses a deterministic planner so the Agent can be validated without
    API keys or network calls.
    """

    def __init__(self, *, use_external_model: bool | None = None, mode: str | None = None) -> None:
        self.config = PlannerConfig(mode=mode) if mode else PlannerConfig.from_env()
        if use_external_model is not None:
            self.config = PlannerConfig(mode="llm" if use_external_model else "mock")
        self.use_external_model = bool(
            use_external_model if use_external_model is not None else os.getenv("LLM_PLANNER_USE_MODEL", "").lower() in {"1", "true", "yes"}
        )
        self.tool_calling_mode = str(os.getenv("TOOL_CALLING_MODE", "json") or "json").strip().lower()
        self.rule_router = HighConfidenceRuleRouter()

    def plan(self, normalized: NormalizedMessage, catalog: ToolCatalog) -> PlannerOutput:
        if self.config.disabled:
            return self._fallback_plan("LLM_PLANNER_MODE=off，交回旧路由。")
        if self.config.mode == "hybrid":
            rule_output = self.rule_router.route(normalized, catalog)
            if rule_output is not None:
                return rule_output
        if self.config.external_allowed and (self.use_external_model or self.config.external_required):
            try:
                return self._plan_with_model(normalized, catalog)
            except Exception as exc:
                if self.config.external_required:
                    raise
                fallback = self._plan_with_rules(normalized)
                fallback.raw = json.dumps(
                    {
                        "external_error": str(exc),
                        "fallback_raw": fallback.raw,
                    },
                    ensure_ascii=False,
                )
                fallback.source = "hybrid_mock_fallback"
                return fallback
        if self.config.mock_allowed:
            return self._plan_with_rules(normalized)
        return self._fallback_plan("Planner mode 不允许 mock fallback。")

    def _plan_with_model(self, normalized: NormalizedMessage, catalog: ToolCatalog) -> PlannerOutput:
        from backend.services.llm_service import LLMService

        prompt = self._build_prompt(normalized, catalog)
        result = LLMService(
            provider_id=normalized.provider_id,
            model_id=normalized.model_id,
            user_id=normalized.user_id,
            conversation_id=normalized.conversation_id,
        ).generate_general_reply(prompt)
        raw = str(result.get("reply") or "").strip()
        payload, repaired = self._parse_json(raw)
        return PlannerOutput(plan=LLMPlan.from_dict(payload), raw=raw if repaired == raw else repaired, source=f"external_llm:{self.tool_calling_mode}")

    def _build_prompt(self, normalized: NormalizedMessage, catalog: ToolCatalog) -> str:
        lines = [
                "你是 RamanAgent 的工具规划器。只输出 JSON，不要输出 Markdown。",
                "必须从工具目录中选择 tool_name/action_name，不能编造工具。",
                "LLM 输出不会直接执行，会经过 PlanValidator。",
                f"TOOL_CALLING_MODE={self.tool_calling_mode}。当前阶段 native function calling 未强制启用，必要时回退为 JSON plan。",
                "输出格式：",
                '{"plan_type":"model|tool|skill|rag|raman_pipeline|hybrid|fallback","intent":"...","confidence":0.0,"requires_file":true,"requires_confirmation":false,"reason":"...","steps":[{"step_id":"step_001","tool_name":"raman_pipeline","action_name":"run_custom_pipeline","args":{}}]}',
                f"工具目录：{json.dumps(catalog.to_prompt_payload(), ensure_ascii=False)}",
                f"用户消息：{normalized.message}",
                f"has_file：{normalized.has_file}",
                f"file_type：{normalized.file_type}",
        ]
        if self.tool_calling_mode in {"auto", "native"}:
            from .function_calling_adapter import FunctionCallingAdapter

            lines.append(f"OpenAI-compatible tools schema：{json.dumps(FunctionCallingAdapter.to_openai_tools(catalog, strict=True), ensure_ascii=False)}")
        return "\n".join(lines)

    def _parse_json(self, raw: str) -> tuple[dict[str, Any], str]:
        return loads_json_with_repair(raw)

    def _fallback_plan(self, reason: str) -> PlannerOutput:
        payload = {
            "plan_type": "fallback",
            "intent": "unknown",
            "confidence": 0.2,
            "requires_file": False,
            "requires_confirmation": False,
            "reason": reason,
            "steps": [],
        }
        return PlannerOutput(plan=LLMPlan.from_dict(payload), raw=json.dumps(payload, ensure_ascii=False), source="planner_fallback")

    def _plan_with_rules(self, normalized: NormalizedMessage) -> PlannerOutput:
        text = str(normalized.message or "").strip()
        lowered = text.lower()

        def raw(payload: dict[str, Any]) -> PlannerOutput:
            raw_text = json.dumps(payload, ensure_ascii=False)
            return PlannerOutput(plan=LLMPlan.from_dict(payload), raw=raw_text, source="deterministic_mock")

        if self._mentions_deep_learning_denoise(text, lowered):
            return raw(
                {
                    "plan_type": "raman_pipeline",
                    "intent": "raman_deep_learning_denoise",
                    "confidence": 0.86,
                    "requires_file": True,
                    "requires_confirmation": False,
                    "reason": "用户要求使用深度学习去噪，规划为深度学习去噪占位 Pipeline。",
                    "steps": [
                        {
                            "step_id": "step_001",
                            "tool_name": "raman_pipeline",
                            "action_name": "run_custom_pipeline",
                            "args": {
                                "steps": [
                                    {"algorithm_id": "load_csv_spectrum", "params": {}},
                                    {"algorithm_id": "validate_spectrum_csv", "params": {}},
                                    {"algorithm_id": "autoencoder_denoise", "params": {}},
                                ]
                            },
                        }
                    ],
                }
            )

        if self._mentions_preprocess_compare(text, lowered):
            return raw(
                {
                    "plan_type": "raman_pipeline",
                    "intent": "raman_preprocessing_compare",
                    "confidence": 0.88,
                    "requires_file": True,
                    "requires_confirmation": False,
                    "reason": "用户要求比较不同预处理方法对结果的影响。",
                    "steps": [
                        {
                            "step_id": "step_001",
                            "tool_name": "raman_pipeline",
                            "action_name": "compare_pipelines",
                            "args": {
                                "pipelines": [
                                    {"template_id": "basic_preprocessing"},
                                    {
                                        "steps": [
                                            {"algorithm_id": "load_csv_spectrum", "params": {}},
                                            {"algorithm_id": "remove_nan_inf", "params": {}},
                                            {"algorithm_id": "sort_by_wavenumber", "params": {}},
                                            {"algorithm_id": "moving_average", "params": {"window_size": 7}},
                                            {"algorithm_id": "z_score_normalize", "params": {}},
                                        ]
                                    },
                                    {
                                        "steps": [
                                            {"algorithm_id": "load_csv_spectrum", "params": {}},
                                            {"algorithm_id": "remove_nan_inf", "params": {}},
                                            {"algorithm_id": "sort_by_wavenumber", "params": {}},
                                            {"algorithm_id": "gaussian_filter", "params": {"sigma": 1.2}},
                                            {"algorithm_id": "min_max_normalize", "params": {}},
                                        ]
                                    },
                                ]
                            },
                        }
                    ],
                }
            )

        if self._mentions_no_prediction_preprocess(text, lowered):
            return raw(
                {
                    "plan_type": "raman_pipeline",
                    "intent": "raman_preprocess_only",
                    "confidence": 0.9,
                    "requires_file": True,
                    "requires_confirmation": False,
                    "reason": "用户明确说先不要预测，只做预处理并画图。",
                    "steps": [
                        {
                            "step_id": "step_001",
                            "tool_name": "raman_pipeline",
                            "action_name": "run_template_pipeline",
                            "args": {"template_id": "basic_preprocessing"},
                        }
                    ],
                }
            )

        if self._mentions_peak_analysis(text, lowered):
            return raw(
                {
                    "plan_type": "raman_pipeline",
                    "intent": "raman_peak_analysis",
                    "confidence": 0.9,
                    "requires_file": True,
                    "requires_confirmation": False,
                    "reason": "用户要求查找主要峰位并标出。",
                    "steps": [
                        {
                            "step_id": "step_001",
                            "tool_name": "raman_pipeline",
                            "action_name": "run_template_pipeline",
                            "args": {"template_id": "peak_analysis"},
                        }
                    ],
                }
            )

        if self._mentions_quality(text, lowered):
            return raw(
                {
                    "plan_type": "raman_pipeline",
                    "intent": "raman_quality_check",
                    "confidence": 0.9,
                    "requires_file": True,
                    "requires_confirmation": False,
                    "reason": "用户询问光谱质量。",
                    "steps": [
                        {
                            "step_id": "step_001",
                            "tool_name": "raman_pipeline",
                            "action_name": "run_template_pipeline",
                            "args": {"template_id": "quality_check"},
                        }
                    ],
                }
            )

        if self._mentions_methanol_prediction(text, lowered):
            return raw(
                {
                    "plan_type": "hybrid",
                    "intent": "methanol_prediction",
                    "confidence": 0.88,
                    "requires_file": True,
                    "requires_confirmation": False,
                    "reason": "用户要求使用甲醇预测流程分析 CSV。",
                    "steps": [
                        {
                            "step_id": "step_001",
                            "tool_name": "raman_pipeline",
                            "action_name": "run_template_pipeline",
                            "args": {"template_id": "methanol_prediction"},
                        },
                        {
                            "step_id": "step_002",
                            "tool_name": "raman_model",
                            "action_name": "predict_methanol_concentration",
                            "args": {},
                        },
                    ],
                }
            )

        if self._mentions_sg_smoothing(text, lowered):
            return raw(
                {
                    "plan_type": "raman_pipeline",
                    "intent": "raman_sg_smoothing",
                    "confidence": 0.84,
                    "requires_file": True,
                    "requires_confirmation": False,
                    "reason": "用户要求对光谱执行 SG 平滑。",
                    "steps": [
                        {
                            "step_id": "step_001",
                            "tool_name": "raman_pipeline",
                            "action_name": "run_custom_pipeline",
                            "args": {
                                "steps": [
                                    {"algorithm_id": "load_csv_spectrum", "params": {}},
                                    {"algorithm_id": "validate_spectrum_csv", "params": {}},
                                    {"algorithm_id": "savitzky_golay", "params": {"window_length": 11, "polyorder": 2}},
                                ]
                            },
                        }
                    ],
                }
            )

        if self._mentions_custom_preprocessing(text, lowered):
            return raw(
                {
                    "plan_type": "raman_pipeline",
                    "intent": "raman_custom_preprocessing",
                    "confidence": 0.9,
                    "requires_file": True,
                    "requires_confirmation": False,
                    "reason": "用户指定了 SG 平滑、ALS 去基线和 z-score 归一化。",
                    "steps": [
                        {
                            "step_id": "step_001",
                            "tool_name": "raman_pipeline",
                            "action_name": "run_custom_pipeline",
                            "args": {
                                "steps": [
                                    {"algorithm_id": "load_csv_spectrum", "params": {}},
                                    {"algorithm_id": "validate_spectrum_csv", "params": {}},
                                    {"algorithm_id": "remove_nan_inf", "params": {}},
                                    {"algorithm_id": "sort_by_wavenumber", "params": {}},
                                    {"algorithm_id": "remove_duplicate_wavenumber", "params": {}},
                                    {"algorithm_id": "savitzky_golay", "params": {"window_length": 11, "polyorder": 2}},
                                    {"algorithm_id": "als_baseline", "params": {"lam": 100000.0, "p": 0.01, "iterations": 10}},
                                    {"algorithm_id": "baseline_subtraction", "params": {"clip_negative": True}},
                                    {"algorithm_id": "z_score_normalize", "params": {}},
                                ]
                            },
                        }
                    ],
                }
            )

        return raw(
            {
                "plan_type": "fallback",
                "intent": "unknown",
                "confidence": 0.2,
                "requires_file": False,
                "requires_confirmation": False,
                "reason": "没有生成可靠增强计划，交回旧路由。",
                "steps": [],
            }
        )

    def _mentions_custom_preprocessing(self, text: str, lowered: str) -> bool:
        return ("sg" in lowered or "savitzky" in lowered or "平滑" in text) and ("als" in lowered or "去基线" in text or "基线" in text) and (
            "z-score" in lowered or "zscore" in lowered or "z score" in lowered or "归一化" in text
        )

    def _mentions_quality(self, text: str, lowered: str) -> bool:
        return "质量" in text or "信噪比" in text or "snr" in lowered or "噪声" in text

    def _mentions_peak_analysis(self, text: str, lowered: str) -> bool:
        return ("峰位" in text or "主要峰" in text or "标出来" in text or "标出" in text or "peak" in lowered) and "深度学习" not in text

    def _mentions_methanol_prediction(self, text: str, lowered: str) -> bool:
        return "甲醇" in text and ("预测" in text or "分析" in text or "csv" in lowered)

    def _mentions_preprocess_compare(self, text: str, lowered: str) -> bool:
        return ("比较" in text or "对比" in text) and ("预处理" in text or "平滑" in text or "归一化" in text)

    def _mentions_no_prediction_preprocess(self, text: str, lowered: str) -> bool:
        return ("不要预测" in text or "先不预测" in text or "不做预测" in text) and ("预处理" in text or "画图" in text or "绘图" in text)

    def _mentions_deep_learning_denoise(self, text: str, lowered: str) -> bool:
        return ("深度学习" in text or "deep learning" in lowered or "autoencoder" in lowered or "cdae" in lowered) and ("去噪" in text or "denoise" in lowered)

    def _mentions_sg_smoothing(self, text: str, lowered: str) -> bool:
        if "als" in lowered or "去基线" in text or "归一化" in text or "z-score" in lowered or "zscore" in lowered:
            return False
        return ("sg" in lowered or "savitzky" in lowered or "平滑" in text) and ("光谱" in text or "raman" in lowered or "spectrum" in lowered)
