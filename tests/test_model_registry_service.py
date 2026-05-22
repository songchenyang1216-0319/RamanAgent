from pathlib import Path
import json
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.services.model_registry_service import ModelRegistryService


REQUIRED_FILES = [
    "cdae_display_model.pt",
    "cdae_reg_model.pt",
    "caeplus_model.pt",
    "svr_model.pkl",
    "rf_model.pkl",
    "scaler.pkl",
    "common_axis.npy",
    "latent_train.npy",
    "config.json",
]


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _touch_required_files(directory: Path, file_names: list[str] | None = None) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name in file_names or REQUIRED_FILES:
        (directory / name).write_text("x", encoding="utf-8")


def _build_service(tmp_path: Path, registry_payload: dict) -> ModelRegistryService:
    artifacts_root = tmp_path / "artifacts"
    registry_path = artifacts_root / "model_registry.json"
    _write_json(registry_path, registry_payload)
    return ModelRegistryService(
        registry_path=registry_path,
        artifacts_root=artifacts_root,
        project_root=tmp_path,
    )


def test_get_default_model_reads_new_registry_structure(tmp_path):
    registry_payload = {
        "default_model": "methanol_v1",
        "models": {
            "methanol_v1": {
                "model_name": "Test Model",
                "task": "methanol_concentration_prediction",
                "artifact_dir": "artifacts/methanol_v1",
                "legacy_artifact_dir": "artifacts",
                "required_files": REQUIRED_FILES,
                "metrics": {"rmse": 0.2, "mae": 0.1, "r2": 0.99},
            }
        },
    }
    _touch_required_files(tmp_path / "artifacts" / "methanol_v1")
    _write_json(tmp_path / "artifacts" / "methanol_v1" / "metrics.json", {"rmse": 0.2, "mae": 0.1, "r2": 0.99})

    service = _build_service(tmp_path, registry_payload)
    result = service.get_default_model()

    assert result["success"] is True
    assert result["data"]["model_version"] == "methanol_v1"
    assert result["data"]["artifact_dir"] == "artifacts/methanol_v1"
    assert result["data"]["metrics"]["rmse"] == 0.2


def test_list_models_returns_default_model_and_metrics(tmp_path):
    registry_payload = {
        "default_model": "methanol_v1",
        "models": {
            "methanol_v1": {
                "model_name": "Test Model",
                "task": "methanol_concentration_prediction",
                "artifact_dir": "artifacts/methanol_v1",
                "required_files": REQUIRED_FILES,
                "metrics": {"rmse": None, "mae": None, "r2": None},
            }
        },
    }
    _touch_required_files(tmp_path / "artifacts" / "methanol_v1")
    _write_json(tmp_path / "artifacts" / "methanol_v1" / "metrics.json", {"rmse": 0.3, "mae": 0.2, "r2": 0.95})

    service = _build_service(tmp_path, registry_payload)
    result = service.list_models()

    assert result["success"] is True
    assert result["default_model"] == "methanol_v1"
    assert len(result["data"]) == 1
    assert result["data"][0]["metrics"]["r2"] == 0.95


def test_validate_model_files_reports_missing_files(tmp_path):
    registry_payload = {
        "default_model": "methanol_v1",
        "models": {
            "methanol_v1": {
                "artifact_dir": "artifacts/methanol_v1",
                "required_files": REQUIRED_FILES,
            }
        },
    }
    _touch_required_files(tmp_path / "artifacts" / "methanol_v1", ["config.json", "svr_model.pkl"])

    service = _build_service(tmp_path, registry_payload)
    result = service.check_model_artifacts()

    assert result["success"] is False
    assert result["data"]["missing_files"]
    assert any("缺失文件" in warning for warning in result["warnings"])


def test_legacy_root_artifacts_structure_is_still_supported(tmp_path):
    registry_payload = {
        "current_model_version": "methanol_v1",
        "models": [
            {
                "model_version": "methanol_v1",
                "artifact_dir": "artifacts/methanol_v1",
                "legacy_artifact_dir": "artifacts",
                "required_files": REQUIRED_FILES,
            }
        ],
    }
    _touch_required_files(tmp_path / "artifacts")

    service = _build_service(tmp_path, registry_payload)
    result = service.check_model_artifacts()

    assert result["success"] is True
    assert result["data"]["fallback_files"]
    assert any("兼容加载" in warning for warning in result["warnings"])
