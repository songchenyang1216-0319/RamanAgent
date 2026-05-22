from pathlib import Path
import os
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.services.llm_service import LLMService


def test_llm_service_no_key():
    old_value = os.environ.pop("SILICONFLOW_API_KEY", None)
    try:
        service = LLMService()
        message = service.explain_methanol_result(
            {
                "sample_file": "sample.csv",
                "fusion_prediction": 0.12,
                "svr_prediction": 0.10,
                "rf_prediction": 0.14,
                "unit": "%",
                "confidence": {"status": "可信度正常"},
                "model_disagreement": {"warning": False, "message": "SVR 与 RF 预测差异在可接受范围内。"},
                "pipeline": ["统一波数轴", "SG平滑"],
                "result_summary": {"prediction_text": "融合预测结果为 0.1200 %"},
            }
        )
        assert "未配置 SILICONFLOW_API_KEY" in message

        general_reply = service.generate_general_reply("你好", {"current_model_version": "methanol_v1"})
        assert general_reply["reply"]
        assert "Traceback" not in general_reply["reply"]
    finally:
        if old_value is not None:
            os.environ["SILICONFLOW_API_KEY"] = old_value


if __name__ == "__main__":
    test_llm_service_no_key()
    print("llm service no key test passed")
