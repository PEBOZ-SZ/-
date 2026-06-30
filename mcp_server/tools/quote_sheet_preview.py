from __future__ import annotations

from typing import Any
from urllib.parse import quote

import quote_upload_storage
from mcp_server.audit import write_audit_log
from mcp_server.auth import ROLE_ADMIN, ROLE_SALES, ROLE_SYSTEM_ADMIN, require_tool_permission
from mcp_server.sanitizer import sanitize_quote_sheet_preview_result
from mcp_server.schemas import normalize_user_context, validate_quote_sheet_preview_input
from quote_sheet_prefill import build_quote_sheet_prefill_payload_for_mcp


TOOL_NAME = "quote_sheet_preview"
SAFE_NOT_FOUND = "报价不存在或无权访问。"


def _failure(error: str) -> dict[str, Any]:
    return {"ok": False, "tool": TOOL_NAME, "error": error}


def _audit_record(
    user_context: dict[str, Any],
    query: dict[str, Any],
    result: dict[str, Any] | None = None,
    success: bool = False,
    error: str | None = None,
) -> dict[str, Any]:
    result_dict = result if isinstance(result, dict) else {}
    summary = result_dict.get("prefill_summary") if isinstance(result_dict.get("prefill_summary"), dict) else {}
    return {
        "tool": TOOL_NAME,
        "user_id": user_context.get("user_id"),
        "role": user_context.get("role", "guest"),
        "session_id": user_context.get("session_id"),
        "sales_user_id": user_context.get("sales_user_id"),
        "quote_uid": result_dict.get("quote_uid") or query.get("quote_uid") or "",
        "calc_quote_id": result_dict.get("calc_quote_id") or query.get("calc_quote_id") or "",
        "version_id": result_dict.get("version_id") or query.get("version_id"),
        "version_no": result_dict.get("version_no") or query.get("version_no"),
        "mode": query.get("mode"),
        "include_prefill": query.get("include_prefill"),
        "rows_count": summary.get("rows_count"),
        "success": success,
        "error": error,
    }


def _resolve_detail(query: dict[str, Any]) -> dict[str, Any] | None:
    return quote_upload_storage.load_quote_detail_for_mcp(
        quote_uid=query["quote_uid"],
        calc_quote_id=query["calc_quote_id"],
        version_id=query["version_id"],
        version_no=query["version_no"],
        include_quote_json=True,
        include_files=False,
        include_chat_messages=False,
    )


def _needs_user_completion(meta: dict[str, Any]) -> list[str]:
    needs: list[str] = []
    checks = [
        ("payee_account", ("payee_account_type", "payee_account_id", "payee_company_name")),
        ("sample_required", ("sample_required",)),
        ("sample_fee", ("sample_fee",)),
        ("sample_lead_time", ("sample_lead_time",)),
    ]
    for label, keys in checks:
        value_present = any(str(meta.get(key) or "").strip() for key in keys)
        if label == "sample_required":
            value_present = str(meta.get("sample_required") or "").strip().lower() in {"yes", "no"}
        if not value_present:
            needs.append(label)
    return needs


def _prefill_summary(prefill: dict[str, Any]) -> dict[str, Any]:
    meta = prefill.get("meta") if isinstance(prefill.get("meta"), dict) else {}
    rows = prefill.get("rows") if isinstance(prefill.get("rows"), list) else []
    return {
        "quote_no": str(meta.get("quote_no") or ""),
        "customer_name": str(meta.get("cust_name") or ""),
        "product_name": str(prefill.get("product_name") or ""),
        "rows_count": len(rows),
        "has_images": any(
            isinstance(row, dict) and bool(str(row.get("image_data_url") or "").strip())
            for row in rows
        ),
        "suggested_export_lang": str(prefill.get("suggested_export_lang") or "cn"),
        "fob_quote": bool(prefill.get("fob_quote")),
        "needs_user_completion": _needs_user_completion(meta),
    }


def quote_sheet_preview(input_data: dict) -> dict:
    user_context = normalize_user_context(
        input_data.get("user_context") if isinstance(input_data, dict) else {}
    )
    query: dict[str, Any] = {}
    result: dict[str, Any] | None = None
    try:
        require_tool_permission(user_context, TOOL_NAME)
        user_context, query = validate_quote_sheet_preview_input(input_data)

        role = str(user_context.get("role") or "guest")
        sales_user_id = str(user_context.get("sales_user_id") or "").strip()
        if role == ROLE_SALES and not sales_user_id:
            raise ValueError("role=sales requires sales_user_id.")

        detail = _resolve_detail(query)
        if not detail:
            raise PermissionError(SAFE_NOT_FOUND)

        quote_uid = str(detail.get("quote_uid") or "").strip()
        if role == ROLE_SALES and not quote_upload_storage.sales_user_can_access_quote(quote_uid, sales_user_id):
            raise PermissionError(SAFE_NOT_FOUND)
        allow_admin = role in {ROLE_ADMIN, ROLE_SYSTEM_ADMIN}
        prefill = build_quote_sheet_prefill_payload_for_mcp(
            quote_uid,
            sales_user_id=sales_user_id,
            allow_admin=allow_admin,
            source=query["source"],
        )
        if not isinstance(prefill, dict) or not prefill.get("ok"):
            raise PermissionError(SAFE_NOT_FOUND)

        include_prefill = query["mode"] == "prefill" or bool(query["include_prefill"])
        result = {
            "quote_uid": quote_uid,
            "calc_quote_id": str(detail.get("calc_quote_id") or ""),
            "version_id": detail.get("version_id"),
            "version_no": detail.get("version_no"),
            "product_name": str(detail.get("product_name") or prefill.get("product_name") or ""),
            "approval_status": str(detail.get("approval_status") or "pending"),
            "preview_url": f"/?view=quoteSheet&quote_uid={quote(quote_uid)}",
            "prefill_available": True,
            "prefill_summary": _prefill_summary(prefill),
        }
        if include_prefill:
            result["prefill"] = prefill

        write_audit_log(_audit_record(user_context, query, result=result, success=True))
        return {
            "ok": True,
            "tool": TOOL_NAME,
            "result": sanitize_quote_sheet_preview_result(result, role),
        }
    except Exception as exc:  # noqa: BLE001
        error = SAFE_NOT_FOUND if isinstance(exc, PermissionError) and str(exc) == SAFE_NOT_FOUND else str(exc)
        try:
            write_audit_log(_audit_record(user_context, query, result=result, success=False, error=error))
        except Exception:
            pass
        return _failure(error)
