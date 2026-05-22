from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.knowledge.raman_peaks import annotate_peaks, find_peak_annotations


def test_methanol_peak_annotations_are_cautious():
    annotations = find_peak_annotations(1030.0)

    assert annotations
    joined = " ".join(str(item) for item in annotations)
    assert "可能" in joined or "通常" in joined
    assert "确定检出" not in joined
    assert "就是甲醇" not in joined
    assert all(item["confidence"] in {"possible", "caution", "unknown"} for item in annotations)


def test_unknown_peak_does_not_overclaim():
    annotations = find_peak_annotations(900.0)

    assert annotations[0]["label"] == "unassigned"
    assert "不做确定成分归属" in annotations[0]["caution"]


def test_annotate_peaks_keeps_original_fields():
    peaks = [{"wavenumber": 1032.0, "intensity": 1.2, "rank": 1}]

    annotated = annotate_peaks(peaks)

    assert annotated[0]["rank"] == 1
    assert annotated[0]["knowledge_annotations"]
