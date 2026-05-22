from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.model_registry.model_registry_router import router
from backend.model_registry.model_registry_service import ModelRegistryService


def test_model_registry_service():
    service = ModelRegistryService()

    loaded = service.load_registry()
    assert loaded["success"] is True

    current = service.get_current_model()
    assert current["success"] is True
    assert current["data"]["model_version"] == "methanol_v1"

    models = service.list_models()
    assert models["success"] is True
    assert isinstance(models["data"], list)

    check = service.check_model_artifacts("methanol_v1")
    assert "existing_files" in check["data"]
    assert "missing_files" in check["data"]

    missing = service.get_model_version("not_exists")
    assert missing["success"] is False

    assert router is not None


if __name__ == "__main__":
    test_model_registry_service()
    print("model registry test passed")
