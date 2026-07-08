from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote

import quote_upload_storage
from mcp_server.audit import write_audit_log
from mcp_server.auth import require_tool_permission
from mcp_server.sanitizer import sanitize_quote_sheet_preview_result
from mcp_server.schemas import normalize_user_context, validate_quote_sheet_preview_input
from quote_sheet_direct_prefill import build_direct_quote_sheet_prefill_payload
from quote_sheet_prefill import build_quote_sheet_prefill_payload_for_mcp
from quote_sheet_public_store import save_public_quote_sheet_prefill


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


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _has_direct_quote_sheet_payload(query: Any) -> bool:
    if not isinstance(query, dict):
        return False
    return any(key in query for key in ("prefill", "quote_sheet", "quote_sheet_rows", "rows", "products", "items"))


def _direct_query_from_input(input_data: Any) -> dict[str, Any] | None:
    if not isinstance(input_data, dict):
        return None
    query = input_data.get("query")
    if _has_direct_quote_sheet_payload(query):
        return query
    if _has_direct_quote_sheet_payload(input_data):
        return input_data
    return None


def _public_base_url() -> str:
    for key in ("PUBLIC_MCP_BASE_URL", "AUTOQUOTE_PUBLIC_BASE_URL", "RENDER_EXTERNAL_URL"):
        value = str(os.environ.get(key) or "").strip().rstrip("/")
        if value:
            return value
    hostname = str(os.environ.get("RENDER_EXTERNAL_HOSTNAME") or "").strip().strip("/")
    if hostname:
        return f"https://{hostname}"
    service_name = str(os.environ.get("RENDER_SERVICE_NAME") or "").strip()
    if service_name:
        return f"https://{service_name}.onrender.com"
    return ""


def _absolute_or_relative_url(path: str) -> str:
    base = _public_base_url()
    return f"{base}{path}" if base else path


def _direct_preview(query: dict[str, Any]) -> dict[str, Any]:
    prefill = build_direct_quote_sheet_prefill_payload(query)
    token = save_public_quote_sheet_prefill(prefill)
    quoted_token = quote(token)
    preview_path = f"/?view=quoteSheet&quote_sheet_token={quoted_token}"
    download_path = f"{preview_path}&exportMode=pdf_rmb"
    if str(query.get("export_mode") or query.get("exportMode") or "").strip().lower() == "pdf_fob":
        download_path = f"{preview_path}&exportMode=pdf_fob"
    include_prefill = (
        str(query.get("mode") or "").strip().lower() == "prefill"
        or _coerce_bool(query.get("include_prefill"), False)
    )
    result = {
        "quote_uid": "",
        "calc_quote_id": "",
        "version_id": None,
        "version_no": None,
        "product_name": str(prefill.get("product_name") or ""),
        "approval_status": "not_required",
        "preview_token": token,
        "preview_url": _absolute_or_relative_url(preview_path),
        "download_url": _absolute_or_relative_url(download_path),
        "prefill_available": True,
        "prefill_summary": _prefill_summary(prefill),
    }
    if include_prefill:
        result["prefill"] = prefill
    return {
        "ok": True,
        "tool": TOOL_NAME,
        "result": result,
    }


def quote_sheet_preview(input_data: dict) -> dict:
    user_context = normalize_user_context(
        input_data.get("user_context") if isinstance(input_data, dict) else {}
    )
    query: dict[str, Any] = {}
    result: dict[str, Any] | None = None
    try:
        direct_query = _direct_query_from_input(input_data)
        if direct_query is not None:
            return _direct_preview(direct_query)

        require_tool_permission(user_context, TOOL_NAME)
        user_context, query = validate_quote_sheet_preview_input(input_data)

        role = str(user_context.get("role") or "guest")
        sales_user_id = str(user_context.get("sales_user_id") or "").strip()

        detail = _resolve_detail(query)
        if not detail:
            raise PermissionError(SAFE_NOT_FOUND)

        quote_uid = str(detail.get("quote_uid") or "").strip()
        prefill = build_quote_sheet_prefill_payload_for_mcp(
            quote_uid,
            sales_user_id=sales_user_id,
            allow_admin=True,
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
