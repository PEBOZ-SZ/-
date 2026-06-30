from __future__ import annotations

from typing import Any

import quote_upload_storage
from mcp_server.audit import write_audit_log
from mcp_server.auth import ROLE_SALES, require_tool_permission
from mcp_server.sanitizer import sanitize_quote_get_detail_result
from mcp_server.schemas import normalize_user_context, validate_quote_get_detail_input


TOOL_NAME = "quote_get_detail"
SAFE_NOT_FOUND = "报价不存在或无权访问。"


def _audit_record(
    user_context: dict[str, Any],
    query: dict[str, Any],
    result: dict[str, Any] | None = None,
    success: bool = False,
    error: str | None = None,
) -> dict[str, Any]:
    result_dict = result if isinstance(result, dict) else {}
    return {
        "tool": TOOL_NAME,
        "user_id": user_context.get("user_id"),
        "role": user_context.get("role", "guest"),
        "session_id": user_context.get("session_id"),
        "sales_user_id": user_context.get("sales_user_id"),
        "quote_uid": result_dict.get("quote_uid") or query.get("quote_uid") or "",
        "calc_quote_id": result_dict.get("calc_quote_id") or query.get("calc_quote_id") or "",
        "version_no": result_dict.get("version_no") or query.get("version_no"),
        "include_files": query.get("include_files"),
        "include_chat_messages": query.get("include_chat_messages"),
        "success": success,
        "error": error,
    }


def _failure(error: str) -> dict[str, Any]:
    return {"ok": False, "tool": TOOL_NAME, "error": error}


def quote_get_detail(input_data: dict) -> dict:
    user_context = normalize_user_context(
        input_data.get("user_context") if isinstance(input_data, dict) else {}
    )
    query: dict[str, Any] = {}
    result: dict[str, Any] | None = None
    try:
        require_tool_permission(user_context, TOOL_NAME)
        user_context, query = validate_quote_get_detail_input(input_data)

        role = str(user_context.get("role") or "guest")
        sales_user_id = str(user_context.get("sales_user_id") or "").strip()
        if role == ROLE_SALES and not sales_user_id:
            raise ValueError("role=sales 查询报价详情必须提供 sales_user_id。")

        result = quote_upload_storage.load_quote_detail_for_mcp(
            quote_uid=query["quote_uid"],
            calc_quote_id=query["calc_quote_id"],
            version_id=query["version_id"],
            version_no=query["version_no"],
            include_quote_json=query["include_quote_json"],
            include_files=query["include_files"],
            include_chat_messages=query["include_chat_messages"],
        )
        if not result:
            raise PermissionError(SAFE_NOT_FOUND)
        result["include_chat_messages"] = bool(query["include_chat_messages"])
        quote_uid = str(result.get("quote_uid") or "").strip()
        if role == ROLE_SALES and not quote_upload_storage.sales_user_can_access_quote(quote_uid, sales_user_id):
            raise PermissionError(SAFE_NOT_FOUND)

        write_audit_log(_audit_record(user_context, query, result=result, success=True))
        return {
            "ok": True,
            "tool": TOOL_NAME,
            "result": sanitize_quote_get_detail_result(result, role),
        }
    except Exception as exc:  # noqa: BLE001
        error = SAFE_NOT_FOUND if isinstance(exc, PermissionError) else str(exc)
        try:
            write_audit_log(_audit_record(user_context, query, result=result, success=False, error=error))
        except Exception:
            pass
        return _failure(error)
