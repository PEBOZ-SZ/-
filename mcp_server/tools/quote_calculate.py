from __future__ import annotations

from typing import Any

from mcp_server.audit import write_audit_log
from mcp_server.auth import require_tool_permission
from mcp_server.sanitizer import sanitize_quote_result
from mcp_server.schemas import normalize_user_context, validate_quote_calculate_input


TOOL_NAME = "quote_calculate"
MODE = "preview"


def _audit_record(
    user_context: dict[str, Any],
    payload: Any,
    success: bool,
    error: str | None = None,
) -> dict[str, Any]:
    payload_dict = payload if isinstance(payload, dict) else {}
    items = payload_dict.get("items")
    quantities = payload_dict.get("quantities")
    return {
        "tool": TOOL_NAME,
        "user_id": user_context.get("user_id"),
        "role": user_context.get("role", "guest"),
        "session_id": user_context.get("session_id"),
        "items_count": len(items) if isinstance(items, list) else 0,
        "quantities": quantities if quantities is not None else None,
        "success": success,
        "error": error,
    }


def _failure(error: str) -> dict[str, Any]:
    return {
        "ok": False,
        "tool": TOOL_NAME,
        "mode": MODE,
        "error": error,
    }


def quote_calculate(input_data: dict) -> dict:
    user_context = normalize_user_context(
        input_data.get("user_context") if isinstance(input_data, dict) else {}
    )
    payload = input_data.get("payload") if isinstance(input_data, dict) else None

    try:
        require_tool_permission(user_context, TOOL_NAME)
        user_context, payload = validate_quote_calculate_input(input_data)

        from quotation_agent.calculator_bridge import run_calculate_quote

        result = run_calculate_quote(payload)
        sanitized = sanitize_quote_result(result, user_context.get("role", "sales"))
        write_audit_log(_audit_record(user_context, payload, success=True))
        return {
            "ok": True,
            "tool": TOOL_NAME,
            "mode": MODE,
            "result": sanitized,
        }
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
        try:
            write_audit_log(_audit_record(user_context, payload, success=False, error=error))
        except Exception:
            pass
        return _failure(error)
