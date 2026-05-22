"""模型版本注册与工件解析服务。"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from backend.model_registry.model_metadata import (
    DEFAULT_MODEL_REGISTRY,
    DEFAULT_MODEL_VERSION,
    DEFAULT_REQUIRED_FILES,
)
from raman_core.methanol.config import ARTIFACT_DIR, PROJECT_ROOT, ensure_dirs


REGISTRY_PATH = ARTIFACT_DIR / "model_registry.json"


class ModelRegistryService:
    """负责读取模型注册表，并兼容旧版 artifacts 根目录结构。"""

    def __init__(
        self,
        registry_path: Path | None = None,
        artifacts_root: Path | None = None,
        project_root: Path | None = None,
    ) -> None:
        self.project_root = Path(project_root) if project_root is not None else PROJECT_ROOT
        self.artifacts_root = Path(artifacts_root) if artifacts_root is not None else ARTIFACT_DIR
        self.registry_path = Path(registry_path) if registry_path is not None else REGISTRY_PATH

    def _success(self, data: Any = None, warnings: list[str] | None = None, **extra: Any) -> dict:
        payload = {"success": True, "data": data, "warnings": warnings or [], "error_message": None}
        payload.update(extra)
        return payload

    def _failure(self, message: str, warnings: list[str] | None = None, **extra: Any) -> dict:
        payload = {"success": False, "data": None, "warnings": warnings or [], "error_message": message}
        payload.update(extra)
        return payload

    def _ensure_registry_file(self) -> None:
        ensure_dirs()
        self.artifacts_root.mkdir(parents=True, exist_ok=True)
        if not self.registry_path.exists():
            self.registry_path.write_text(
                json.dumps(DEFAULT_MODEL_REGISTRY, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def _normalize_model_entry(self, model_id: str, raw: dict[str, Any]) -> dict[str, Any]:
        entry = deepcopy(raw)
        entry.setdefault("model_version", model_id)
        entry.setdefault("task", entry.pop("target", "methanol_concentration_prediction"))
        entry.setdefault("artifact_dir", f"artifacts/{model_id}")
        entry.setdefault("legacy_artifact_dir", "artifacts")
        entry.setdefault("status", "active")
        entry.setdefault("required_files", list(DEFAULT_REQUIRED_FILES))
        entry.setdefault("metrics", {"rmse": None, "mae": None, "r2": None})
        entry.setdefault("training_data", {})
        entry.setdefault("notes", "")
        entry.setdefault("config_file", "config.json")
        entry.setdefault("metrics_file", "metrics.json")
        entry.setdefault("training_meta_file", "training_meta.json")
        return entry

    def _normalize_registry(self, raw: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        warnings: list[str] = []
        if "default_model" in raw and isinstance(raw.get("models"), dict):
            normalized_models = {
                str(model_id): self._normalize_model_entry(str(model_id), model_data or {})
                for model_id, model_data in dict(raw.get("models") or {}).items()
            }
            default_model = str(raw.get("default_model") or DEFAULT_MODEL_VERSION)
            if default_model not in normalized_models and normalized_models:
                default_model = next(iter(normalized_models))
                warnings.append("default_model 不在 models 中，已自动回退到第一个已注册模型。")
            if not normalized_models:
                normalized_models = deepcopy(DEFAULT_MODEL_REGISTRY["models"])
                default_model = DEFAULT_MODEL_REGISTRY["default_model"]
                warnings.append("models 为空，已回填默认模型注册信息。")
            return {"default_model": default_model, "models": normalized_models}, warnings

        models_map: dict[str, Any] = {}
        old_models = raw.get("models") or []
        if isinstance(old_models, list):
            for item in old_models:
                if not isinstance(item, dict):
                    continue
                model_id = str(item.get("model_version") or item.get("id") or DEFAULT_MODEL_VERSION)
                models_map[model_id] = self._normalize_model_entry(model_id, item)
        if not models_map:
            models_map = deepcopy(DEFAULT_MODEL_REGISTRY["models"])
        default_model = str(raw.get("current_model_version") or raw.get("default_model") or next(iter(models_map)))
        warnings.append("检测到旧版 model_registry.json 结构，已自动升级为 default_model + models 对象格式。")
        return {"default_model": default_model, "models": models_map}, warnings

    def _relative(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.project_root)).replace("\\", "/")
        except ValueError:
            return str(path.name)

    def _artifact_dir_path(self, model_id: str, model: dict[str, Any]) -> Path:
        artifact_dir = Path(str(model.get("artifact_dir") or f"artifacts/{model_id}"))
        if artifact_dir.is_absolute():
            return artifact_dir
        return self.project_root / artifact_dir

    def _legacy_dir_path(self, model: dict[str, Any]) -> Path:
        legacy_dir = Path(str(model.get("legacy_artifact_dir") or "artifacts"))
        if legacy_dir.is_absolute():
            return legacy_dir
        return self.project_root / legacy_dir

    def _resolve_artifact_with_source(self, model_id: str, filename: str) -> tuple[Path | None, str]:
        model_response = self.get_model(model_id)
        if not model_response["success"]:
            return None, "missing"
        model = model_response["data"] or {}
        primary_dir = self._artifact_dir_path(model_id, model)
        primary_path = primary_dir / filename
        if primary_path.exists():
            return primary_path, "versioned"
        legacy_path = self._legacy_dir_path(model) / filename
        if legacy_path.exists():
            return legacy_path, "legacy"
        return primary_path, "missing"

    def _load_json_if_exists(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    def _read_metrics(self, model_id: str, model: dict[str, Any]) -> dict[str, Any]:
        metrics = deepcopy(model.get("metrics") or {})
        metrics_path = self._artifact_dir_path(model_id, model) / str(model.get("metrics_file") or "metrics.json")
        file_metrics = self._load_json_if_exists(metrics_path)
        if file_metrics:
            metrics.update(file_metrics)
        return metrics

    def _read_training_meta(self, model_id: str, model: dict[str, Any]) -> dict[str, Any] | None:
        candidates = [
            self._artifact_dir_path(model_id, model) / str(model.get("training_meta_file") or "training_meta.json"),
            self._artifact_dir_path(model_id, model) / "training_meta.example.json",
        ]
        for path in candidates:
            meta = self._load_json_if_exists(path)
            if meta:
                return meta
        return None

    def _build_public_model(self, model_id: str, model: dict[str, Any], validation: dict | None = None) -> dict[str, Any]:
        validation = validation or self.validate_model_files(model_id)
        validation_data = validation.get("data") or {}
        return {
            "model_version": model_id,
            "task": model.get("task"),
            "model_name": model.get("model_name"),
            "status": model.get("status", "active"),
            "unit": model.get("unit"),
            "artifact_dir": str(model.get("artifact_dir") or f"artifacts/{model_id}"),
            "created_at": model.get("created_at"),
            "notes": model.get("notes"),
            "metrics": self._read_metrics(model_id, model),
            "training_data": deepcopy(model.get("training_data") or {}),
            "preprocessing_pipeline": list(model.get("preprocessing_pipeline") or []),
            "required_files": list(model.get("required_files") or DEFAULT_REQUIRED_FILES),
            "missing_files": list(validation_data.get("missing_files") or []),
            "fallback_files": list(validation_data.get("fallback_files") or []),
            "is_default": bool(validation_data.get("model_version") == self.load_registry()["data"].get("default_model")),
        }

    def load_registry(self) -> dict:
        """读取模型注册表，不存在时创建默认内容；旧结构会自动归一化。"""
        try:
            self._ensure_registry_file()
            raw = json.loads(self.registry_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return self._failure("model_registry.json 格式错误，顶层必须是对象。")
            normalized, warnings = self._normalize_registry(raw)
            if normalized != raw:
                self.registry_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
            return self._success(normalized, warnings)
        except json.JSONDecodeError as exc:
            return self._failure(f"model_registry.json 解析失败: {exc}")
        except Exception as exc:
            return self._failure(f"读取模型注册表失败: {exc}")

    def get_default_model_id(self) -> str | None:
        loaded = self.load_registry()
        if not loaded["success"]:
            return None
        return str((loaded.get("data") or {}).get("default_model"))

    def list_models(self) -> dict:
        loaded = self.load_registry()
        if not loaded["success"]:
            return loaded
        registry = loaded["data"] or {}
        models_map = registry.get("models") or {}
        models = []
        warnings = list(loaded.get("warnings") or [])
        for model_id, model in models_map.items():
            validation = self.validate_model_files(str(model_id))
            models.append(self._build_public_model(str(model_id), model, validation=validation))
            warnings.extend(validation.get("warnings") or [])
        return self._success(models, list(dict.fromkeys(warnings)), default_model=registry.get("default_model"))

    def get_model(self, model_id: str) -> dict:
        loaded = self.load_registry()
        if not loaded["success"]:
            return loaded
        models = (loaded["data"] or {}).get("models") or {}
        model = models.get(model_id)
        if model is None:
            return self._failure(f"未找到模型版本: {model_id}")
        return self._success(deepcopy(model), loaded["warnings"], model_id=model_id)

    def get_default_model(self) -> dict:
        default_model = self.get_default_model_id()
        if not default_model:
            return self._failure("未找到默认模型。")
        model = self.get_model(default_model)
        if not model["success"]:
            return model
        validation = self.validate_model_files(default_model)
        return self._success(
            self._build_public_model(default_model, model["data"] or {}, validation=validation),
            list(dict.fromkeys((model.get("warnings") or []) + (validation.get("warnings") or []))),
        )

    def get_model_config(self, model_id: str) -> dict:
        model_response = self.get_model(model_id)
        if not model_response["success"]:
            return model_response
        model = model_response["data"] or {}
        config_name = str(model.get("config_file") or "config.json")
        config_path = self.resolve_artifact_path(model_id, config_name)
        if config_path is None:
            return self._failure(f"未找到模型配置文件: {config_name}")
        config = self._load_json_if_exists(config_path)
        if config is None:
            return self._failure(f"模型配置文件无法读取: {self._relative(config_path)}")
        payload = {
            "model_version": model_id,
            "artifact_dir": str(model.get("artifact_dir") or f"artifacts/{model_id}"),
            "config_file": config_name,
            "config": config,
            "metrics": self._read_metrics(model_id, model),
            "training_meta": self._read_training_meta(model_id, model),
        }
        return self._success(payload, model_response.get("warnings", []))

    def resolve_artifact_path(self, model_id: str, filename: str) -> Path | None:
        path, source = self._resolve_artifact_with_source(model_id, filename)
        if source == "missing":
            return None
        return path

    def validate_model_files(self, model_id: str) -> dict:
        model_response = self.get_model(model_id)
        if not model_response["success"]:
            return model_response
        model = model_response["data"] or {}
        required_files = list(model.get("required_files") or DEFAULT_REQUIRED_FILES)
        existing_files = []
        missing_files = []
        fallback_files = []
        warnings = list(model_response.get("warnings") or [])

        for filename in required_files:
            path, source = self._resolve_artifact_with_source(model_id, filename)
            expected_relative = self._relative(self._artifact_dir_path(model_id, model) / filename)
            record = {"name": filename, "path": expected_relative}
            if source == "missing" or path is None:
                missing_files.append(record)
                continue
            found_relative = self._relative(path)
            record["resolved_path"] = found_relative
            existing_files.append(record)
            if source == "legacy":
                fallback_files.append(record)

        if fallback_files:
            warnings.append("当前模型部分文件仍通过旧版 artifacts 根目录兼容加载。")
        if missing_files:
            warnings.append("当前模型仍有缺失文件，请补齐版本目录或旧版根目录工件。")

        return self._success(
            {
                "model_version": model_id,
                "artifact_dir": str(model.get("artifact_dir") or f"artifacts/{model_id}"),
                "existing_files": existing_files,
                "missing_files": missing_files,
                "fallback_files": fallback_files,
            },
            list(dict.fromkeys(warnings)),
        )

    def set_default_model(self, model_id: str) -> dict:
        loaded = self.load_registry()
        if not loaded["success"]:
            return loaded
        registry = loaded["data"] or {}
        if model_id not in (registry.get("models") or {}):
            return self._failure(f"未找到模型版本: {model_id}")
        registry["default_model"] = model_id
        try:
            self.registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            return self._failure(f"写入模型注册表失败: {exc}")
        return self.get_default_model()

    # 兼容旧命名，避免现有调用方失效。
    def get_current_model(self) -> dict:
        return self.get_default_model()

    def get_model_version(self, model_version: str) -> dict:
        model = self.get_model(model_version)
        if not model["success"]:
            return model
        validation = self.validate_model_files(model_version)
        return self._success(
            self._build_public_model(model_version, model["data"] or {}, validation=validation),
            list(dict.fromkeys((model.get("warnings") or []) + (validation.get("warnings") or []))),
        )

    def check_model_artifacts(self, model_version: str | None = None) -> dict:
        target = model_version or self.get_default_model_id()
        if not target:
            return self._failure("未找到默认模型。")
        validation = self.validate_model_files(target)
        if not validation["success"]:
            return validation
        data = validation.get("data") or {}
        success = len(data.get("missing_files") or []) == 0
        return {
            "success": success,
            "data": data,
            "warnings": validation.get("warnings", []),
            "error_message": None if success else "模型工件存在缺失文件。",
        }

    def set_current_model(self, model_version: str) -> dict:
        return self.set_default_model(model_version)
