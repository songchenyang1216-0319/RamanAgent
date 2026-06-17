from __future__ import annotations

from backend.raman_pipeline.adapters.ramanspy_adapter import RamanSPyAdapter


def test_ramanspy_adapter_reports_availability_without_crashing() -> None:
    adapter = RamanSPyAdapter()
    status = adapter.status()
    assert "available" in status
    assert "ramanspy_savgol" in status["algorithms"]
    specs = adapter.algorithm_specs()
    assert any(spec.algorithm_id == "ramanspy_savgol" for spec in specs)
    if not adapter.available:
        assert specs[0].available is False
        assert specs[0].unavailable_reason
