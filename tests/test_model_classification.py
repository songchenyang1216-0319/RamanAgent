from backend.core.model_registry import ModelRegistry
from backend.core.model_router import ModelRouter


def test_known_models_have_expected_categories():
    registry = ModelRegistry()
    cases = {
        ("sensenova", "sensenova-6.7-flash-lite"): ["text_chat", "vision_understanding"],
        ("qwen", "qwen3.6-plus"): ["text_chat", "vision_understanding"],
        ("qwen", "qwen-image-edit-plus"): ["image_edit"],
        ("gemini", "gemini-2.5-flash"): ["text_chat", "vision_understanding"],
    }
    for (provider_id, model_id), expected in cases.items():
        meta = registry.get_model_meta(provider_id, model_id)
        assert meta["supported_categories"] == expected
        assert meta["supported_category_labels"]
        assert meta["category_summary"]


def test_vision_models_are_listed_with_category_metadata():
    registry = ModelRegistry()
    vision_models = registry.list_available_vision_models()
    ids = {item["model_id"] for item in vision_models}
    assert "sensenova-6.7-flash-lite" in ids
    assert "qwen3.6-plus" in ids
    assert "gemini-2.5-flash" in ids
    for item in vision_models:
        assert item["supported_categories"]
        assert item["supported_category_labels"]
        assert item["category_summary"]


def test_model_router_exposes_category_metadata():
    router = ModelRouter()
    selection = router.resolve_selection(provider_id="qwen", model_id="qwen3.6-plus")
    assert selection["model_type"] == "vision"
    assert selection["supports_vision"] is True
    assert selection["supported_categories"] == ["text_chat", "vision_understanding"]
    assert selection["supported_category_labels"] == ["文本对话", "视觉理解"]
    assert selection["category_summary"] == "文本对话 / 视觉理解"


def test_text_models_keep_text_category():
    registry = ModelRegistry()
    meta = registry.get_model_meta("openai", "gpt-5.4")
    assert meta["supported_categories"] == ["text_chat"]
    assert meta["supported_category_labels"] == ["文本对话"]
    assert meta["supports_vision"] is False
