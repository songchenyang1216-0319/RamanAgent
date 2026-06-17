from __future__ import annotations

from backend.agent.planning.function_calling_adapter import FunctionCallingAdapter, FunctionToolCall
from backend.agent.planning.tool_catalog import ToolCatalog


def test_function_calling_adapter_exports_openai_schema() -> None:
    tool = ToolCatalog().get("raman_pipeline")
    assert tool is not None
    action = tool.get_action("run_template_pipeline")
    assert action is not None
    schema = FunctionCallingAdapter.to_openai_function(tool, action, strict=True)
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "raman_pipeline__run_template_pipeline"
    assert schema["function"]["parameters"]["type"] == "object"
    assert schema["function"]["parameters"]["additionalProperties"] is False
    assert schema["function"]["strict"] is True


def test_function_calling_adapter_parallel_tool_calls() -> None:
    payload = FunctionCallingAdapter.parallel_tool_calls(
        [FunctionToolCall(id="call_001", name="raman_pipeline__list_algorithms")]
    )
    assert payload["parallel"] is True
    assert payload["tool_calls"][0]["id"] == "call_001"


def test_function_calling_adapter_exports_catalog_and_parses_openai_calls() -> None:
    catalog = ToolCatalog()
    tools = FunctionCallingAdapter.to_openai_tools(catalog, strict=True)
    assert any(item["function"]["name"] == "raman_pipeline__list_algorithms" for item in tools)
    qwen_tools = FunctionCallingAdapter.to_qwen_tools(catalog)
    deepseek_tools = FunctionCallingAdapter.to_deepseek_tools(catalog)
    generic_schema = FunctionCallingAdapter.to_generic_json_schema(catalog, strict=True)
    assert qwen_tools and deepseek_tools
    assert generic_schema["x-ramanagent-tools"]
    calls = FunctionCallingAdapter.parse_tool_calls(
        {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "call_a",
                                "function": {
                                    "name": "raman_pipeline__list_algorithms",
                                    "arguments": "{\"limit\": 1}",
                                },
                            }
                        ]
                    }
                }
            ]
        },
        provider="openai",
    )
    assert calls[0].id == "call_a"
    assert calls[0].arguments["limit"] == 1
    assert FunctionCallingAdapter.from_function_name(calls[0].name) == ("raman_pipeline", "list_algorithms")
