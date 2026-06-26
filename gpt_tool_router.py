from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from mcp_server.tools.quote_admin import quote_admin
from mcp_server.tools.quote_calculate import quote_calculate
from mcp_server.tools.quote_explain import quote_explain
from mcp_server.tools.quote_export import quote_export
from mcp_server.tools.quote_patch_preview import quote_patch_preview
from mcp_server.tools.quote_save import quote_save
from workflow_state_manager import (
    flow_error_response,
    log_workflow_event,
    transition_state,
    validate_tool_call,
    workflow_state_from_input,
)


GPT_TOOL_TRACE_PATH = Path("logs") / "gpt_tool_trace.jsonl"
DEFAULT_MODEL = "gpt-4.1-mini"


GPT_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "quote_calculate",
            "description": "Preview a quote by calling the existing MCP quote_calculate tool. Do not calculate prices yourself.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_context": {"type": "object"},
                    "payload": {
                        "type": "object",
                        "properties": {
                            "product_name": {"type": "string"},
                            "quantities": {"type": "array", "items": {"type": "number"}},
                            "items": {"type": "array", "items": {"type": "object"}},
                        },
                        "required": ["items"],
                    },
                },
                "required": ["payload"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "quote_explain",
            "description": "Explain an existing quote_result through the MCP quote_explain tool.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_context": {"type": "object"},
                    "query": {
                        "type": "object",
                        "properties": {
                            "user_question": {"type": "string"},
                            "quote_result": {"type": "object"},
                            "audience": {"type": "string"},
                        },
                        "required": ["user_question", "quote_result"],
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "quote_patch_preview",
            "description": "Preview local changes to an existing quote_result using MCP quote_patch_preview.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_context": {"type": "object"},
                    "query": {
                        "type": "object",
                        "properties": {
                            "quote_result": {"type": "object"},
                            "patch": {"type": "object"},
                        },
                        "required": ["quote_result"],
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "quote_save",
            "description": "Save an existing quote_result through MCP quote_save.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_context": {"type": "object"},
                    "query": {
                        "type": "object",
                        "properties": {"quote_result": {"type": "object"}},
                        "required": ["quote_result"],
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "quote_export",
            "description": "Export a saved quote by quote_id through MCP quote_export.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_context": {"type": "object"},
                    "query": {
                        "type": "object",
                        "properties": {"quote_id": {"type": "string"}},
                        "required": ["quote_id"],
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "quote_admin",
            "description": "Run admin actions such as approve, reject, freeze, unfreeze, mark_exported, or view through MCP quote_admin.",
            "parameters": {
                "type": "object",
                "properties": {
                    "user_context": {"type": "object"},
                    "query": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string"},
                            "quote_id": {"type": "string"},
                            "payload": {"type": "object"},
                        },
                        "required": ["action"],
                    },
                },
                "required": ["query"],
            },
        },
    },
]


def _now_iso() -> str:
    return datetime.now().isoformat()


def _tool_map() -> dict[str, Callable[[dict], dict]]:
    return {
        "quote_calculate": quote_calculate,
        "quote_explain": quote_explain,
        "quote_patch_preview": quote_patch_preview,
        "quote_save": quote_save,
        "quote_export": quote_export,
        "quote_admin": quote_admin,
    }


def _message_from_response(response: Any) -> dict[str, Any]:
    if isinstance(response, dict):
        message = response.get("message")
        if isinstance(message, dict):
            return message
        choices = response.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict) and isinstance(first.get("message"), dict):
                return first["message"]
    message = getattr(response, "message", None)
    if isinstance(message, dict):
        return message
    choices = getattr(response, "choices", None)
    if choices:
        first = choices[0]
        msg = getattr(first, "message", None)
        if msg is not None:
            return _object_message_to_dict(msg)
    return {}


def _object_message_to_dict(message: Any) -> dict[str, Any]:
    if isinstance(message, dict):
        return message
    result: dict[str, Any] = {}
    content = getattr(message, "content", None)
    if content is not None:
        result["content"] = content
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls is not None:
        result["tool_calls"] = [_object_tool_call_to_dict(call) for call in tool_calls]
    return result


def _object_tool_call_to_dict(call: Any) -> dict[str, Any]:
    if isinstance(call, dict):
        return call
    function = getattr(call, "function", None)
    return {
        "id": getattr(call, "id", ""),
        "function": {
            "name": getattr(function, "name", ""),
            "arguments": getattr(function, "arguments", "{}"),
        },
    }


def _tool_calls_from_message(message: dict[str, Any]) -> list[dict[str, Any]]:
    raw_calls = message.get("tool_calls")
    if not isinstance(raw_calls, list):
        return []
    return [_object_tool_call_to_dict(call) for call in raw_calls]


def _parse_arguments(raw_arguments: Any) -> dict[str, Any]:
    if isinstance(raw_arguments, dict):
        return raw_arguments
    if not raw_arguments:
        return {}
    value = json.loads(str(raw_arguments))
    if not isinstance(value, dict):
        raise ValueError("tool arguments must be a JSON object")
    return value


def _write_trace(
    *,
    user_input: str,
    gpt_decision: dict[str, Any],
    tool_called: str,
    tool_arguments: dict[str, Any],
    result: dict[str, Any],
    success: bool,
) -> None:
    GPT_TOOL_TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "user_input": user_input,
        "gpt_decision": gpt_decision,
        "tool_called": tool_called,
        "tool_arguments": tool_arguments,
        "result": result,
        "timestamp": _now_iso(),
        "success": success,
    }
    with GPT_TOOL_TRACE_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


class OpenAIToolCallingClient:
    def __init__(self, model: str = DEFAULT_MODEL):
        self.model = model

    def create(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Any:
        from openai import OpenAI

        client = OpenAI()
        return client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
        )


def run_gpt_tool_agent(
    user_input: str,
    context: dict | None = None,
    client: Any | None = None,
    max_steps: int = 4,
) -> dict[str, Any]:
    active_client = client or OpenAIToolCallingClient()
    context_dict = context if isinstance(context, dict) else {}
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "You are a GPT tool-calling controller for an MCP quote system. "
                "Always call the provided MCP tools for quote operations. "
                "Never calculate prices directly."
            ),
        },
        {
            "role": "user",
            "content": str(user_input or ""),
        },
    ]
    if context_dict:
        messages.append(
            {
                "role": "system",
                "content": "Runtime context JSON: " + json.dumps(context_dict, ensure_ascii=False, default=str),
            }
        )

    executed: list[dict[str, Any]] = []
    final_message: dict[str, Any] = {}
    tools = _tool_map()
    current_workflow_state = workflow_state_from_input(context_dict)

    try:
        for _ in range(max_steps):
            response = active_client.create(messages=messages, tools=GPT_TOOL_SCHEMAS)
            message = _message_from_response(response)
            final_message = message
            tool_calls = _tool_calls_from_message(message)
            if not tool_calls:
                break
            messages.append(message)
            for call in tool_calls:
                function = call.get("function") if isinstance(call.get("function"), dict) else {}
                name = str(function.get("name") or "")
                arguments = _parse_arguments(function.get("arguments", "{}"))
                if name not in tools:
                    raise ValueError(f"unsupported tool call: {name}")
                arguments.setdefault("workflow_state", current_workflow_state)
                try:
                    validate_tool_call(name, arguments)
                except PermissionError as exc:
                    result = flow_error_response(name, exc)
                else:
                    result = tools[name](arguments)
                success = bool(result.get("ok")) if isinstance(result, dict) else False
                if success:
                    try:
                        current_workflow_state = transition_state(current_workflow_state, name)
                    except PermissionError:
                        pass
                else:
                    log_workflow_event(
                        "tool call blocked" if result.get("workflow_error") else "tool call failed",
                        state=current_workflow_state,
                        tool=name,
                        detail={"result": result},
                    )
                call_record = {
                    "tool_called": name,
                    "tool_arguments": arguments,
                    "result": result,
                    "workflow_state": current_workflow_state,
                }
                executed.append(call_record)
                _write_trace(
                    user_input=str(user_input or ""),
                    gpt_decision=call,
                    tool_called=name,
                    tool_arguments=arguments,
                    result=result,
                    success=success,
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": str(call.get("id") or name),
                        "name": name,
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    }
                )
        return {
            "ok": all(bool(call["result"].get("ok")) for call in executed) if executed else False,
            "tool_calls": executed,
            "final_message": final_message.get("content") or "",
        }
    except Exception as exc:  # noqa: BLE001
        error = {"ok": False, "error": str(exc)}
        _write_trace(
            user_input=str(user_input or ""),
            gpt_decision=final_message,
            tool_called="",
            tool_arguments={},
            result=error,
            success=False,
        )
        return {"ok": False, "tool_calls": executed, "error": str(exc)}
