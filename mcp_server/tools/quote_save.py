from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import quote_upload_storage
from mcp_server.audit import write_audit_log
from mcp_server.auth import require_tool_permission
from mcp_server.sanitizer import sanitize_quote_save_result
from mcp_server.schemas import normalize_user_context, validate_quote_save_input


TOOL_NAME = "quote_save"
QUOTE_SAVE_STORE_PATH = Path("data") / "mcp_saved_quotes.jsonl"


def _extract_total_price(quote_result: dict[str, Any]) -> float | None:
    for key in ("total_price", "exw_price", "fob_price", "total"):
        try:
            value = quote_result.get(key)
            if value is not None:
                return round(float(value), 2)
        except (TypeError, ValueError):
            pass
    tiers = quote_result.get("tiers")
    if isinstance(tiers, list):
        for tier in tiers:
            if not isinstance(tier, dict):
                continue
            for key in ("total_price", "exw_price", "fob_price", "total"):
                try:
                    value = tier.get(key)
                    if value is not None:
                        return round(float(value), 2)
                except (TypeError, ValueError):
                    pass
    return None


def _coerce_optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError("query.base_version_no 必须是整数或空值。") from None


def _query_dict(input_data: dict) -> dict[str, Any]:
    query = input_data.get("query") if isinstance(input_data, dict) else None
    return query if isinstance(query, dict) else {}


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _persistence_args(
    input_data: dict,
    user_context: dict[str, Any],
    quote_result: dict[str, Any],
) -> dict[str, Any]:
    query = _query_dict(input_data)
    calc_quote_id = _first_text(quote_result.get("quote_id"))
    if not calc_quote_id:
        raise ValueError("query.quote_result.quote_id 不能为空，无法接入原系统持久化。")

    quote_series_uid = _first_text(
        query.get("quote_series_uid"),
        quote_result.get("quote_series_uid"),
        quote_result.get("quote_uid"),
        calc_quote_id,
    )
    uploaded_sheet = query.get("uploaded_sheet")
    if uploaded_sheet is not None and not isinstance(uploaded_sheet, dict):
        raise ValueError("query.uploaded_sheet 必须是 dict 或空值。")
    structured_input = query.get("structured_input")
    if structured_input is None:
        structured_input = quote_result.get("structured_input")
    if structured_input is not None and not isinstance(structured_input, dict):
        raise ValueError("query.structured_input 必须是 dict 或空值。")

    source_summary = query.get("source_summary")
    if source_summary is None:
        source_summary = quote_result.get("source_summary")
    if source_summary is not None and not isinstance(source_summary, dict):
        raise ValueError("query.source_summary 必须是 dict 或空值。")

    sheet_name = _first_text(
        query.get("sheet_original_display_name"),
        query.get("sheet_original_name"),
        uploaded_sheet.get("name") if isinstance(uploaded_sheet, dict) else None,
        quote_result.get("sheet_original_display_name"),
        quote_result.get("sheet_original_name"),
    )

    return {
        "quote_series_uid": quote_series_uid,
        "quote_result": quote_result,
        "uploaded_sheet": uploaded_sheet,
        "sheet_original_display_name": sheet_name,
        "sales_user_id": _first_text(user_context.get("sales_user_id"), user_context.get("user_id")) or None,
        "sales_user_name": _first_text(user_context.get("sales_user_name"), user_context.get("user_name")) or None,
        "structured_input": structured_input,
        "quote_mode": _first_text(query.get("quote_mode"), quote_result.get("quote_mode")) or None,
        "validation_status": _first_text(
            query.get("validation_status"),
            quote_result.get("validation_status"),
        )
        or None,
        "base_version_no": _coerce_optional_int(
            query.get("base_version_no", quote_result.get("base_version_no"))
        ),
        "base_calc_quote_id": _first_text(
            query.get("base_calc_quote_id"),
            quote_result.get("base_calc_quote_id"),
        )
        or None,
        "patch_id": _first_text(query.get("patch_id"), quote_result.get("patch_id")) or None,
        "source_summary": source_summary,
    }


def _saved_result(args: dict[str, Any]) -> dict[str, Any]:
    quote_result = args["quote_result"]
    quote_uid = str(args["quote_series_uid"] or "").strip()
    quote_id = str(quote_result.get("quote_id") or "").strip()
    latest = quote_upload_storage.resolve_quote_version_target(
        quote_uid,
        calc_quote_id=quote_id,
    )
    latest_dict = latest if isinstance(latest, dict) else {}
    version_no = latest_dict.get("version_no")
    version_id = latest_dict.get("id")
    validation_status = latest_dict.get("validation_status") or args.get("validation_status")
    return {
        "quote_uid": str(latest_dict.get("quote_uid") or quote_uid),
        "quote_id": str(latest_dict.get("calc_quote_id") or quote_id),
        "version_id": version_id,
        "version_no": version_no,
        "status": str(validation_status or "saved"),
        "created_at": str(latest_dict.get("saved_at") or datetime.now().isoformat()),
        "total_price": _extract_total_price(quote_result),
    }


def _audit_record(
    user_context: dict[str, Any],
    result: dict[str, Any] | None,
    success: bool,
    error: str | None = None,
) -> dict[str, Any]:
    result_dict = result if isinstance(result, dict) else {}
    return {
        "tool": TOOL_NAME,
        "user_id": user_context.get("user_id"),
        "role": user_context.get("role", "guest"),
        "session_id": user_context.get("session_id"),
        "quote_uid": result_dict.get("quote_uid"),
        "quote_id": result_dict.get("quote_id"),
        "version_id": result_dict.get("version_id"),
        "total_price": result_dict.get("total_price"),
        "success": success,
        "error": error,
    }


def _failure(error: str) -> dict[str, Any]:
    return {
        "ok": False,
        "tool": TOOL_NAME,
        "error": error,
    }


def quote_save(input_data: dict) -> dict:
    user_context = normalize_user_context(
        input_data.get("user_context") if isinstance(input_data, dict) else {}
    )
    save_result: dict[str, Any] | None = None
    try:
        require_tool_permission(user_context, TOOL_NAME)
        user_context, query = validate_quote_save_input(input_data)

        persistence_args = _persistence_args(input_data, user_context, query["quote_result"])
        quote_upload_storage.finalize_quote_persistence(**persistence_args)
        save_result = _saved_result(persistence_args)
        write_audit_log(_audit_record(user_context, save_result, success=True))
        return {
            "ok": True,
            "tool": TOOL_NAME,
            "result": sanitize_quote_save_result(save_result, user_context.get("role", "sales")),
        }
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
        try:
            write_audit_log(_audit_record(user_context, save_result, success=False, error=error))
        except Exception:
            pass
        return _failure(error)
