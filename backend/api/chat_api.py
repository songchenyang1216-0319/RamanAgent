from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from backend.agent.agent_router import (
    _apply_task_state_from_response,
    _build_session_analysis_payload,
    _ensure_session_id,
    _llm_model_info,
    append_message,
    file_catalog,
    get_session,
    orchestrator,
    task_trace_manager,
    update_session,
    user_memory_manager,
    workspace_manager,
)
from backend.agent.chat_context_builder import ChatContextBuilder
from backend.agent.chat_request_parser import ChatRequestParser
from backend.agent.chat_response_persistence import ChatResponsePersistence
from backend.agent.streaming import format_sse
from backend.services.workspace_manager import DEFAULT_USER_ID
from raman_core.methanol.config import PROJECT_ROOT


router = APIRouter(prefix="/api/agent", tags=["agent-chat"])

chat_request_parser = ChatRequestParser(default_user_id=DEFAULT_USER_ID)
chat_context_builder = ChatContextBuilder(
    workspace_manager=workspace_manager,
    file_catalog=file_catalog,
    user_memory_manager=user_memory_manager,
    ensure_session_id=_ensure_session_id,
    update_session=update_session,
    get_session=get_session,
    project_root=PROJECT_ROOT,
)
chat_response_persistence = ChatResponsePersistence(
    workspace_manager=workspace_manager,
    append_message=append_message,
    update_session=update_session,
    build_session_analysis_payload=_build_session_analysis_payload,
    apply_task_state_from_response=_apply_task_state_from_response,
    llm_model_info=_llm_model_info,
    task_trace_manager=task_trace_manager,
    project_root=PROJECT_ROOT,
)


@router.post("/chat")
async def chat(request: Request) -> dict:
    parsed = await chat_request_parser.parse(request)
    context = await chat_context_builder.build(parsed)
    chat_response_persistence.persist_user_turn(context)
    response_payload = orchestrator.handle_chat(context.to_orchestrator_payload())
    return chat_response_persistence.persist_final_response(context, response_payload)


@router.post("/chat/stream")
async def chat_stream(request: Request) -> StreamingResponse:
    parsed = await chat_request_parser.parse(request)
    context = await chat_context_builder.build(parsed)
    chat_response_persistence.persist_user_turn(context)

    async def event_generator():
        async for event in orchestrator.handle_chat_stream(context.to_orchestrator_payload()):
            if event.event == "final":
                response_payload = dict((event.data or {}).get("response") or {})
                if response_payload:
                    finalized = chat_response_persistence.persist_final_response(context, response_payload)
                    event.data["response"] = finalized
                    event.content = (
                        finalized.get("reply")
                        or finalized.get("llm_explanation")
                        or finalized.get("error_message")
                        or event.content
                    )
            yield format_sse(event)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
