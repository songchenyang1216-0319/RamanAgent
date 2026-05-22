from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from raman_core.methanol.config import ARTIFACT_DIR, DEMO_DATA_DIR
from raman_core.methanol.predictor import MethanolPredictor


def test_predictor_smoke():
    predictor = MethanolPredictor()
    assert predictor is not None
    assert ARTIFACT_DIR.exists()

    demo_files = sorted(DEMO_DATA_DIR.glob("*.csv"))
    if demo_files:
        result = predictor.predict(demo_files[0])
        assert isinstance(result, dict)
        assert "fusion_prediction" in result
        assert "confidence" in result
        assert "figures" in result
    else:
        required_files = [
            "cdae_display_model.pt",
            "cdae_reg_model.pt",
            "caeplus_model.pt",
            "common_axis.npy",
            "latent_train.npy",
            "svr_model.pkl",
            "rf_model.pkl",
            "scaler.pkl",
            "config.json",
        ]
        for file_name in required_files:
            assert (ARTIFACT_DIR / file_name).exists(), f"缺少 artifact: {file_name}"


if __name__ == "__main__":
    test_predictor_smoke()
    print("smoke test passed")
