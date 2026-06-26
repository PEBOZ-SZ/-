from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


WORKFLOW_TRACE_PATH = Path("logs") / "workflow_trace.jsonl"

STATE_INPUT = "INPUT"
STATE_PARSED = "PARSED"
STATE_STRUCTURE_CONFIRM = "STRUCTURE_CONFIRM"
STATE_CONFIRMED = "CONFIRMED"
STATE_CALCULATED = "CALCULATED"
STATE_SAVED = "SAVED"
STATE_EXPORTED = "EXPORTED"

VALID_STATES = {
    STATE_INPUT,
    STATE_PARSED,
    STATE_STRUCTURE_CONFIRM,
    STATE_CONFIRMED,
    STATE_CALCULATED,
    STATE_SAVED,
    STATE_EXPORTED,
}

FLOW_ERROR_STRUCTURE_CONFIRM = "FLOW_ERROR: 请先完成 STRUCTURE_CONFIRM"

TOOL_REQUIRED_STATE = {
    "quote_calculate": STATE_CONFIRMED,
    "quote_save": STATE_CALCULATED,
    "quote_export": STATE_SAVED,
}

TRANSITIONS = {
    (STATE_INPUT, "gpt_parse_structure"): STATE_PARSED,
    (STATE_PARSED, "show_structure_confirm"): STATE_STRUCTURE_CONFIRM,
    (STATE_STRUCTURE_CONFIRM, "user_confirm_structure"): STATE_CONFIRMED,
    (STATE_CONFIRMED, "quote_calculate"): STATE_CALCULATED,
    (STATE_CALCULATED, "quote_save"): STATE_SAVED,
    (STATE_SAVED, "quote_export"): STATE_EXPORTED,
}

STATE_ALIASES = {
    "": STATE_INPUT,
    "input": STATE_INPUT,
    "uploaded": STATE_INPUT,
    "parsed": STATE_PARSED,
    "structure_parse": STATE_PARSED,
    "structure_confirm": STATE_STRUCTURE_CONFIRM,
    "structure_confirmation": STATE_STRUCTURE_CONFIRM,
    "confirmed": STATE_CONFIRMED,
    "calculated": STATE_CALCULATED,
    "saved": STATE_SAVED,
    "exported": STATE_EXPORTED,
}


def now_iso() -> str:
    return datetime.now().isoformat()


def normalize_state(state: Any) -> str:
    text = str(state or "").strip()
    if text in VALID_STATES:
        return text
    return STATE_ALIASES.get(text.lower(), STATE_INPUT)


def workflow_state_from_input(input_data: dict[str, Any] | None) -> str:
    data = input_data if isinstance(input_data, dict) else {}
    for key in ("workflow_state", "state"):
        if key in data:
            return normalize_state(data.get(key))
    query = data.get("query") if isinstance(data.get("query"), dict) else {}
    for key in ("workflow_state", "state"):
        if key in query:
            return normalize_state(query.get(key))
    payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
    for key in ("workflow_state", "state"):
        if key in payload:
            return normalize_state(payload.get(key))
    context = data.get("context") if isinstance(data.get("context"), dict) else {}
    for key in ("workflow_state", "state"):
        if key in context:
            return normalize_state(context.get(key))
    return STATE_INPUT


def transition_state(current_state: Any, action: str) -> str:
    state = normalize_state(current_state)
    next_state = TRANSITIONS.get((state, str(action or "")))
    if not next_state:
        raise PermissionError(FLOW_ERROR_STRUCTURE_CONFIRM)
    log_workflow_event(
        "state transition",
        state=state,
        detail={"action": action, "next_state": next_state},
    )
    return next_state


def validate_tool_call(tool_name: str, input_data: dict[str, Any] | None) -> None:
    required = TOOL_REQUIRED_STATE.get(str(tool_name or ""))
    if not required:
        return
    state = workflow_state_from_input(input_data)
    if state != required:
        log_workflow_event(
            "tool call blocked",
            state=state,
            tool=tool_name,
            detail={"required_state": required, "error": FLOW_ERROR_STRUCTURE_CONFIRM},
        )
        raise PermissionError(FLOW_ERROR_STRUCTURE_CONFIRM)
    log_workflow_event("tool call", state=state, tool=tool_name)


def log_workflow_event(
    event: str,
    *,
    session_id: str | None = None,
    state: str | None = None,
    tool: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    WORKFLOW_TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "event": event,
        "session_id": session_id,
        "state": normalize_state(state),
        "tool": tool,
        "detail": detail or {},
        "timestamp": now_iso(),
    }
    with WORKFLOW_TRACE_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def flow_error_response(tool_name: str, error: Exception) -> dict[str, Any]:
    return {
        "ok": False,
        "tool": tool_name,
        "error": str(error),
        "workflow_error": True,
        "required_step": STATE_STRUCTURE_CONFIRM,
    }
