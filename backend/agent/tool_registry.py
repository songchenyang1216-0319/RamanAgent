"""Agent 工具注册表。"""

from __future__ import annotations

from backend.agent.tools.artifact_tool import check_artifacts_tool
from backend.agent.tools.history_tool import get_history_detail_tool, list_history_tool
from backend.agent.tools.predict_tool import predict_methanol_tool
from backend.agent.tools.report_tool import explain_result_tool, generate_report_tool
from backend.agent.tools.spectral_tools.baseline_quality_tool import analyze_baseline_quality
from backend.agent.tools.spectral_tools.peak_detection_tool import detect_peaks
from backend.agent.tools.spectral_tools.quality_tool import analyze_spectrum_quality
from backend.agent.tools.spectral_tools.similarity_tool import find_similar_history
from backend.agent.tools.spectral_tools.spectral_summary_tool import analyze_spectrum_professionally
from backend.services.model_registry_service import ModelRegistryService


_model_registry_service = ModelRegistryService()


def list_model_versions_tool() -> dict:
    return _model_registry_service.list_models()


def get_current_model_tool() -> dict:
    return _model_registry_service.get_current_model()


def check_current_model_tool() -> dict:
    return _model_registry_service.check_model_artifacts()


TOOL_REGISTRY = {
    "check_artifacts": {
        "name": "check_artifacts",
        "description": "检查 artifacts 目录下模型文件是否齐全",
        "input_schema": {"type": "object", "properties": {}, "required": []},
        "output_schema": {
            "success": "bool",
            "missing_files": "list",
            "existing_files": "list",
            "warnings": "list",
        },
        "handler": check_artifacts_tool,
    },
    "list_history": {
        "name": "list_history",
        "description": "查询历史分析记录",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer"}, "offset": {"type": "integer"}},
            "required": [],
        },
        "output_schema": {"success": "bool", "total": "int", "items": "list"},
        "handler": list_history_tool,
    },
    "get_history_detail": {
        "name": "get_history_detail",
        "description": "根据 history_id 查询历史分析详情",
        "input_schema": {
            "type": "object",
            "properties": {"history_id": {"type": "string"}},
            "required": ["history_id"],
        },
        "output_schema": {"success": "bool", "item": "dict", "error_message": "str|null"},
        "handler": get_history_detail_tool,
    },
    "predict_methanol": {
        "name": "predict_methanol",
        "description": "分析上传的 Raman CSV 文件，返回甲醇预测结果",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "debug": {"type": "boolean"},
            },
            "required": ["file_path"],
        },
        "output_schema": {
            "success": "bool",
            "result": "dict",
            "final_prediction": "float|null",
            "warnings": "list",
        },
        "handler": predict_methanol_tool,
    },
    "generate_report": {
        "name": "generate_report",
        "description": "根据预测结果生成 Markdown 报告",
        "input_schema": {
            "type": "object",
            "properties": {
                "result": {"type": "object"},
                "llm_explanation": {"type": ["string", "null"]},
                "professional_analysis": {"type": "object"},
                "model_info": {"type": "object"},
                "experiment_metadata": {"type": "object"},
            },
            "required": ["result"],
        },
        "output_schema": {
            "success": "bool",
            "report_path": "str|null",
            "report_file": "str|null",
            "report_markdown": "str|null",
        },
        "handler": generate_report_tool,
    },
    "explain_result": {
        "name": "explain_result",
        "description": "根据预测结果生成自然语言解释，必要时返回降级说明",
        "input_schema": {
            "type": "object",
            "properties": {
                "result": {"type": "object"},
                "professional_analysis": {"type": "object"},
                "model_info": {"type": "object"},
                "experiment_metadata": {"type": "object"},
            },
            "required": ["result"],
        },
        "output_schema": {
            "success": "bool",
            "explanation": "str",
            "error_message": "str|null",
        },
        "handler": explain_result_tool,
    },
    "detect_peaks": {
        "name": "detect_peaks",
        "description": "识别 Raman 光谱中的主要峰位",
        "input_schema": {"type": "object", "properties": {"csv_path": {"type": "string"}}, "required": ["csv_path"]},
        "output_schema": {"success": "bool", "peaks": "list", "peak_count": "int", "warnings": "list"},
        "handler": detect_peaks,
    },
    "analyze_spectrum_quality": {
        "name": "analyze_spectrum_quality",
        "description": "评估 Raman 光谱质量、信噪比和异常点",
        "input_schema": {"type": "object", "properties": {"csv_path": {"type": "string"}}, "required": ["csv_path"]},
        "output_schema": {"success": "bool", "quality_level": "str", "metrics": "dict", "warnings": "list"},
        "handler": analyze_spectrum_quality,
    },
    "analyze_baseline_quality": {
        "name": "analyze_baseline_quality",
        "description": "分析基线漂移和预处理质量风险",
        "input_schema": {
            "type": "object",
            "properties": {"csv_path": {"type": "string"}, "prediction_result": {"type": "object"}},
            "required": ["csv_path"],
        },
        "output_schema": {"success": "bool", "baseline_level": "str", "metrics": "dict", "warnings": "list"},
        "handler": analyze_baseline_quality,
    },
    "find_similar_history": {
        "name": "find_similar_history",
        "description": "根据当前预测浓度查找相似历史样品",
        "input_schema": {
            "type": "object",
            "properties": {
                "current_prediction_result": {"type": "object"},
                "limit": {"type": "integer"},
                "max_difference": {"type": "number"},
            },
            "required": ["current_prediction_result"],
        },
        "output_schema": {"success": "bool", "similar_records": "list", "message": "str"},
        "handler": find_similar_history,
    },
    "professional_spectral_analysis": {
        "name": "professional_spectral_analysis",
        "description": "综合峰识别、质量评估、基线判断和历史相似样品比较",
        "input_schema": {
            "type": "object",
            "properties": {"csv_path": {"type": "string"}, "prediction_result": {"type": "object"}},
            "required": ["csv_path"],
        },
        "output_schema": {
            "success": "bool",
            "peak_analysis": "dict",
            "quality_analysis": "dict",
            "baseline_analysis": "dict",
            "professional_summary": "dict",
        },
        "handler": analyze_spectrum_professionally,
    },
    "list_model_versions": {
        "name": "list_model_versions",
        "description": "列出所有已注册模型版本",
        "input_schema": {"type": "object", "properties": {}, "required": []},
        "output_schema": {"success": "bool", "data": "list"},
        "handler": list_model_versions_tool,
    },
    "get_current_model": {
        "name": "get_current_model",
        "description": "获取当前使用的模型版本信息",
        "input_schema": {"type": "object", "properties": {}, "required": []},
        "output_schema": {"success": "bool", "data": "dict"},
        "handler": get_current_model_tool,
    },
    "check_current_model": {
        "name": "check_current_model",
        "description": "检查当前模型版本对应工件是否齐全",
        "input_schema": {"type": "object", "properties": {}, "required": []},
        "output_schema": {"success": "bool", "data": "dict"},
        "handler": check_current_model_tool,
    },
    "get_experiment_history": {
        "name": "get_experiment_history",
        "description": "查询实验记录列表",
        "input_schema": {"type": "object", "properties": {"limit": {"type": "integer"}}, "required": []},
        "output_schema": {"success": "bool", "total": "int", "items": "list"},
        "handler": list_history_tool,
    },
    "get_experiment_detail": {
        "name": "get_experiment_detail",
        "description": "查询单条实验记录详情",
        "input_schema": {"type": "object", "properties": {"history_id": {"type": "string"}}, "required": ["history_id"]},
        "output_schema": {"success": "bool", "item": "dict"},
        "handler": get_history_detail_tool,
    },
}


def list_tool_specs() -> list[dict]:
    """返回工具注册信息列表。"""
    return [
        {
            "name": item["name"],
            "description": item["description"],
            "input_schema": item["input_schema"],
            "output_schema": item["output_schema"],
            "handler_name": getattr(item["handler"], "__name__", ""),
        }
        for item in TOOL_REGISTRY.values()
    ]


def get_tool_spec(tool_name: str) -> dict | None:
    """根据工具名获取工具定义。"""
    return TOOL_REGISTRY.get(tool_name)
