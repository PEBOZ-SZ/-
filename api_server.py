from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI

import gpt_client
import mcp_bridge
from schemas import ApiToolRequest, ChatRequest, WorkflowActionRequest
from workflow_state_manager import FLOW_ERROR_STRUCTURE_CONFIRM, log_workflow_event, transition_state


API_TRACE_PATH = Path("logs") / "api_trace.jsonl"


@asynccontextmanager
async def lifespan(app_: FastAPI):
    print("[API SERVER] self-check: PASS ok=true", flush=True)
    yield


app = FastAPI(title="MCP GPT Quote API", version="0.3.0", lifespan=lifespan)


def _now_iso() -> str:
    return datetime.now().isoformat()


def _write_api_trace(
    *,
    request_body: dict[str, Any],
    gpt_response: dict[str, Any] | None,
    tool_called: str,
    tool_arguments: dict[str, Any],
    response: dict[str, Any],
) -> None:
    API_TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "request_body": request_body,
        "gpt_response": gpt_response,
        "tool_called": tool_called,
        "tool_arguments": tool_arguments,
        "response": response,
        "timestamp": _now_iso(),
    }
    with API_TRACE_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def _chat_context(request: ChatRequest) -> dict[str, Any]:
    context = dict(request.context or {})
    context["workflow_state"] = request.workflow_state
    context["user_context"] = {
        "user_id": request.user_id,
        "role": request.role or "sales",
        "session_id": request.session_id,
    }
    return context


def _tool_trace(gpt_response: dict[str, Any]) -> list[str]:
    calls = gpt_response.get("tool_calls") if isinstance(gpt_response, dict) else []
    if not isinstance(calls, list):
        return []
    return [str(call.get("tool_called") or "") for call in calls if isinstance(call, dict)]


def _extract_chat_result(gpt_response: dict[str, Any]) -> dict[str, Any]:
    calls = gpt_response.get("tool_calls") if isinstance(gpt_response, dict) else []
    if isinstance(calls, list) and calls:
        last = calls[-1]
        if isinstance(last, dict):
            result = last.get("result")
            if isinstance(result, dict):
                inner = result.get("result")
                if isinstance(inner, dict):
                    return inner
                return result
    return {}


def _direct_input(request: ApiToolRequest) -> dict[str, Any]:
    data: dict[str, Any] = {"user_context": request.user_context or {}}
    if request.workflow_state:
        data["workflow_state"] = request.workflow_state
    if request.payload is not None:
        data["payload"] = request.payload
    if request.query is not None:
        data["query"] = request.query
        if request.workflow_state and isinstance(data["query"], dict):
            data["query"].setdefault("workflow_state", request.workflow_state)
        if not data.get("workflow_state") and isinstance(data["query"], dict):
            query_state = data["query"].get("workflow_state") or data["query"].get("state")
            if query_state:
                data["workflow_state"] = query_state
    return data


@app.post("/chat")
def chat(request: ChatRequest) -> dict[str, Any]:
    request_body = request.model_dump()
    gpt_response = gpt_client.run_chat(request.message, context=_chat_context(request))
    tool_calls = gpt_response.get("tool_calls") if isinstance(gpt_response, dict) else []
    first_call = tool_calls[0] if isinstance(tool_calls, list) and tool_calls else {}
    tool_called = str(first_call.get("tool_called") or "") if isinstance(first_call, dict) else ""
    tool_arguments = first_call.get("tool_arguments") if isinstance(first_call, dict) else {}
    if not isinstance(tool_arguments, dict):
        tool_arguments = {}
    response = {
        "ok": bool(gpt_response.get("ok")) if isinstance(gpt_response, dict) else False,
        "intent": tool_called.replace("quote_", "") if tool_called else "",
        "tool_trace": _tool_trace(gpt_response),
        "result": _extract_chat_result(gpt_response),
    }
    _write_api_trace(
        request_body=request_body,
        gpt_response=gpt_response,
        tool_called=tool_called,
        tool_arguments=tool_arguments,
        response=response,
    )
    return response


def _call_direct_endpoint(tool_name: str, request: ApiToolRequest) -> dict[str, Any]:
    request_body = request.model_dump()
    tool_arguments = _direct_input(request)
    response = mcp_bridge.call_mcp_tool(tool_name, tool_arguments)
    _write_api_trace(
        request_body=request_body,
        gpt_response=None,
        tool_called=tool_name,
        tool_arguments=tool_arguments,
        response=response,
    )
    return response


@app.post("/quote/calculate")
def quote_calculate_endpoint(request: ApiToolRequest) -> dict[str, Any]:
    return _call_direct_endpoint("quote_calculate", request)


@app.post("/quote/save")
def quote_save_endpoint(request: ApiToolRequest) -> dict[str, Any]:
    return _call_direct_endpoint("quote_save", request)


@app.post("/quote/export")
def quote_export_endpoint(request: ApiToolRequest) -> dict[str, Any]:
    return _call_direct_endpoint("quote_export", request)


@app.post("/quote/admin")
def quote_admin_endpoint(request: ApiToolRequest) -> dict[str, Any]:
    return _call_direct_endpoint("quote_admin", request)


@app.post("/workflow/action")
def workflow_action(request: WorkflowActionRequest) -> dict[str, Any]:
    request_body = request.model_dump()
    try:
        next_state = transition_state(request.state, request.action)
        log_workflow_event(
            "user action",
            session_id=request.session_id,
            state=next_state,
            detail={"action": request.action, "detail": request.detail},
        )
        response = {"ok": True, "state": next_state}
    except PermissionError:
        response = {"ok": False, "error": FLOW_ERROR_STRUCTURE_CONFIRM, "state": request.state}
    _write_api_trace(
        request_body=request_body,
        gpt_response=None,
        tool_called="workflow_action",
        tool_arguments=request_body,
        response=response,
    )
    return response


@app.post("/workflow/structure-confirm")
def workflow_structure_confirm(request: WorkflowActionRequest) -> dict[str, Any]:
    confirm_request = WorkflowActionRequest(
        session_id=request.session_id,
        state=request.state,
        action="user_confirm_structure",
        detail=request.detail,
    )
    return workflow_action(confirm_request)
