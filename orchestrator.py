from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import mcp_router


ORCHESTRATOR_TRACE_PATH = Path("logs") / "orchestrator_trace.jsonl"
WORKFLOW_STATES = ["intake", "parse", "tool_select", "execute", "assemble", "response"]


def _now_iso() -> str:
    return datetime.now().isoformat()


def _write_trace(record: dict[str, Any]) -> None:
    ORCHESTRATOR_TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"timestamp": _now_iso(), **record}
    with ORCHESTRATOR_TRACE_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def decide_with_gpt(payload: dict[str, Any], state: str) -> dict[str, Any]:
    """Return GPT's structured execution plan only: task/plan[].

    This first-step implementation keeps GPT behind this boundary. If a caller
    injects a real GPT client later, it must still return the same JSON shape.
    """
    raw_decision = payload.get("gpt_decision")
    if isinstance(raw_decision, dict):
        return raw_decision
    return {"task": "chat", "plan": []}


def _validate_gpt_plan(decision: Any) -> dict[str, Any]:
    if not isinstance(decision, dict):
        raise ValueError("GPT plan must be JSON object with task/plan")
    task = str(decision.get("task") or "").strip()
    plan = decision.get("plan")
    if not isinstance(plan, list):
        raise ValueError("GPT plan must include plan array")
    normalized_steps: list[dict[str, Any]] = []
    expected_step = 1
    for raw_step in plan:
        if not isinstance(raw_step, dict):
            raise ValueError("Each plan step must be JSON object")
        step_no = raw_step.get("step")
        if step_no != expected_step:
            raise ValueError("GPT plan steps must be ordered starting at 1")
        tool = str(raw_step.get("tool") or "").strip()
        args = raw_step.get("args")
        if not tool:
            raise ValueError("Each plan step must specify tool")
        if args is None:
            args = {}
        if not isinstance(args, dict):
            raise ValueError("Each plan step args must be JSON object")
        normalized_steps.append({"step": step_no, "tool": tool, "args": args})
        expected_step += 1
    return {"task": task, "plan": normalized_steps}


def _resolve_context_refs(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, str) and value.startswith("$steps."):
        parts = value.split(".")
        current: Any = context
        for part in parts:
            if part == "$steps":
                current = current.get("steps", {})
                continue
            if isinstance(current, dict):
                current = current.get(part)
            else:
                return value
        return current if current is not None else value
    if isinstance(value, dict):
        return {key: _resolve_context_refs(val, context) for key, val in value.items()}
    if isinstance(value, list):
        return [_resolve_context_refs(item, context) for item in value]
    return value


def _execute_plan(plan: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    context: dict[str, Any] = {"steps": {}}
    executed: list[dict[str, Any]] = []
    for step in plan:
        args = _resolve_context_refs(step["args"], context)
        result = mcp_router.mcp_call(step["tool"], args)
        record = {
            "step": step["step"],
            "tool": step["tool"],
            "args": args,
            "result": result,
        }
        executed.append(record)
        context["steps"][str(step["step"])] = {
            "tool": step["tool"],
            "args": args,
            "result": result.get("result") if isinstance(result, dict) and isinstance(result.get("result"), dict) else result,
            "raw_result": result,
        }
        if not (isinstance(result, dict) and result.get("ok")):
            break
    return executed, context


def _assemble_result(decision: dict[str, Any], executed: list[dict[str, Any]], context: dict[str, Any]) -> dict[str, Any]:
    last_result = executed[-1]["result"] if executed else {}
    result = last_result if isinstance(last_result, dict) else {}
    inner = result.get("result") if isinstance(result.get("result"), dict) else result
    return {
        "ok": all(bool(step["result"].get("ok")) for step in executed) if executed else True,
        "task": decision["task"],
        "plan": decision["plan"],
        "tool_trace": [step["tool"] for step in executed],
        "result": inner,
        "steps": executed,
        "context": context,
        "workflow": list(WORKFLOW_STATES),
        "state": "response",
    }


def process(request: dict[str, Any] | None) -> dict[str, Any]:
    payload = request if isinstance(request, dict) else {}
    trace: list[str] = []
    try:
        trace.append("intake")
        _write_trace({"state": "intake", "request": payload})

        trace.append("parse")
        raw_decision = decide_with_gpt(payload, "parse")
        decision = _validate_gpt_plan(raw_decision)
        _write_trace({"state": "parse", "gpt_decision": decision})

        trace.append("tool_select")
        _write_trace({"state": "tool_select", "plan": decision["plan"]})

        trace.append("execute")
        executed, context = _execute_plan(decision["plan"])
        _write_trace({"state": "execute", "steps": executed, "context": context})

        trace.append("assemble")
        response = _assemble_result(decision, executed, context)
        response["workflow"] = list(WORKFLOW_STATES)
        _write_trace({"state": "assemble", "response": response})

        trace.append("response")
        response["state"] = "response"
        return response
    except Exception as exc:  # noqa: BLE001
        error_response = {
            "ok": False,
            "error": str(exc),
            "workflow": trace + [state for state in WORKFLOW_STATES if state not in trace],
            "state": "response",
        }
        _write_trace({"state": "response", "error": str(exc), "workflow": error_response["workflow"]})
        return error_response
