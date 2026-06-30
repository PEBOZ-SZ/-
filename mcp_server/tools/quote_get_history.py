from __future__ import annotations

from typing import Any

import quote_upload_storage
from mcp_server.audit import write_audit_log
from mcp_server.auth import ROLE_SALES, require_tool_permission
from mcp_server.sanitizer import sanitize_quote_get_history_result
from mcp_server.schemas import normalize_user_context, validate_quote_get_history_input


TOOL_NAME = "quote_get_history"


def _audit_record(
    user_context: dict[str, Any],
    query: dict[str, Any],
    count: int = 0,
    success: bool = False,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "tool": TOOL_NAME,
        "user_id": user_context.get("user_id"),
        "role": user_context.get("role", "guest"),
        "session_id": user_context.get("session_id"),
        "sales_user_id": user_context.get("sales_user_id"),
        "limit": query.get("limit"),
        "offset": query.get("offset"),
        "keyword_present": bool(query.get("keyword")),
        "approval_status": query.get("approval_status") or "",
        "count": count,
        "success": success,
        "error": error,
    }


def _failure(error: str) -> dict[str, Any]:
    return {"ok": False, "tool": TOOL_NAME, "error": error}


def quote_get_history(input_data: dict) -> dict:
    user_context = normalize_user_context(
        input_data.get("user_context") if isinstance(input_data, dict) else {}
    )
    query: dict[str, Any] = {}
    count = 0
    try:
        require_tool_permission(user_context, TOOL_NAME)
        user_context, query = validate_quote_get_history_input(input_data)

        role = str(user_context.get("role") or "guest")
        sales_user_id = str(user_context.get("sales_user_id") or "").strip()
        if role == ROLE_SALES and not sales_user_id:
            raise ValueError("role=sales 查询历史报价必须提供 sales_user_id。")
        if role != ROLE_SALES:
            sales_user_id = str(query.get("sales_user_id") or "").strip()

        items, total = quote_upload_storage.list_quote_history_for_mcp(
            role=role,
            sales_user_id=sales_user_id,
            limit=query["limit"],
            offset=query["offset"],
            keyword=query["keyword"],
            approval_status=query["approval_status"],
            include_hidden=bool(query["include_hidden"]),
        )
        result = {
            "items": items,
            "limit": query["limit"],
            "offset": query["offset"],
            "count": len(items),
            "total": total,
        }
        count = len(items)
        write_audit_log(_audit_record(user_context, query, count=count, success=True))
        return {
            "ok": True,
            "tool": TOOL_NAME,
            "result": sanitize_quote_get_history_result(result, role),
        }
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
        try:
            write_audit_log(_audit_record(user_context, query, count=count, success=False, error=error))
        except Exception:
            pass
        return _failure(error)
