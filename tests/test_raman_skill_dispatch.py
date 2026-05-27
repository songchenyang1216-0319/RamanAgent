from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.skills.base import SkillResult
from backend.skills.raman_spectroscopy_skill import RamanSpectroscopySkill


class _DummyAnalysisSkill:
    def run(self, **kwargs):
        assert kwargs["action_name"] == "predict_methanol_concentration"
        assert list(key for key in kwargs if key == "action_name") == ["action_name"]
        return SkillResult(
            success=True,
            skill_name="dummy",
            action_name=kwargs["action_name"],
            summary="ok",
            data={"result": {"final_prediction": 1.0}},
        )


def test_raman_skill_dispatch_removes_duplicate_action_name():
    skill = RamanSpectroscopySkill()
    skill._analysis_skill = _DummyAnalysisSkill()

    result = skill.run(
        action_name="predict_methanol_concentration",
        file_path="sample.csv",
    )

    assert result.success is True
    assert result.action_name == "predict_methanol_concentration"
