from __future__ import annotations

from typing import Any


ALLOWED_QUOTE_RESULT_FIELDS = {
    "product_name",
    "material_total",
    "material_total_text",
    "tiers",
    "items",
    "warnings",
    "review_required",
    "pricing_review_required",
    "structure_checklist",
    "error",
    "payload_attempted",
}

def sanitize_quote_result(result: dict, role: str = "sales") -> dict:
    """Return a whitelist-filtered quote preview result."""
    if not isinstance(result, dict):
        return {"error": "报价引擎返回结果不是 dict。"}

    return {
        key: value
        for key, value in result.items()
        if key in ALLOWED_QUOTE_RESULT_FIELDS
    }


ALLOWED_PRICE_LOOKUP_HIT_FIELDS = {
    "name",
    "spec",
    "price",
    "unit_price_value",
    "unit_price_unit",
    "score",
    "auto_learned",
}


def sanitize_price_lookup_result(result: dict, role: str = "sales") -> dict:
    """Return a whitelist-filtered readonly price lookup result."""
    if not isinstance(result, dict):
        return {"query": {}, "hits": [], "hit_count": 0}

    hits = result.get("hits")
    safe_hits = []
    if isinstance(hits, list):
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            safe_hits.append(
                {
                    key: value
                    for key, value in hit.items()
                    if key in ALLOWED_PRICE_LOOKUP_HIT_FIELDS
                }
            )

    query = result.get("query") if isinstance(result.get("query"), dict) else {}
    return {
        "query": {
            "name": str(query.get("name") or ""),
            "spec": str(query.get("spec") or ""),
        },
        "hits": safe_hits,
        "hit_count": len(safe_hits),
    }


def sanitize_quote_qa_result(result: dict, role: str = "sales") -> dict:
    """Return a whitelist-filtered readonly QA result."""
    if not isinstance(result, dict):
        result = {}

    answer = str(result.get("assistant_message") or result.get("answer") or "").strip()
    if not answer:
        answer = "暂时没有找到可靠答复。"

    sources = result.get("sources")
    qa_sources = result.get("qa_sources")
    return {
        "answer": answer,
        "source_type": str(result.get("source_type") or "fallback"),
        "sources": sources if isinstance(sources, list) else [],
        "qa_sources": qa_sources if isinstance(qa_sources, list) else [],
    }


def sanitize_quote_explain_result(result: dict, role: str = "sales") -> dict:
    """Return a whitelist-filtered readonly quote explanation result."""
    if not isinstance(result, dict):
        result = {}
    answer = str(result.get("answer") or "").strip()
    if not answer:
        answer = "当前报价结果中没有足够信息解释该点。"
    return {
        "answer": answer,
        "audience": str(result.get("audience") or "sales_internal"),
        "used_quote_result": bool(result.get("used_quote_result", True)),
        "number_policy": "quote_result_only",
        "fallback_used": bool(result.get("fallback_used")),
    }


def sanitize_quote_patch_preview_result(result: dict, role: str = "sales") -> dict:
    """Return readonly patch preview result fields only."""
    if not isinstance(result, dict):
        result = {}
    diff = result.get("diff") if isinstance(result.get("diff"), dict) else {}
    return {
        "original_quote": result.get("original_quote") if isinstance(result.get("original_quote"), dict) else {},
        "patched_quote": result.get("patched_quote") if isinstance(result.get("patched_quote"), dict) else {},
        "diff": {
            "changed_fields": diff.get("changed_fields") if isinstance(diff.get("changed_fields"), list) else [],
            "before_total": diff.get("before_total", 0),
            "after_total": diff.get("after_total", 0),
            "delta": diff.get("delta", 0),
            "delta_percent": diff.get("delta_percent", 0),
            "unsupported_fields": diff.get("unsupported_fields")
            if isinstance(diff.get("unsupported_fields"), list)
            else [],
        },
    }


def sanitize_quote_save_result(result: dict, role: str = "sales") -> dict:
    """Return quote_save public fields only."""
    if not isinstance(result, dict):
        result = {}
    return {
        "quote_uid": str(result.get("quote_uid") or ""),
        "quote_id": str(result.get("quote_id") or ""),
        "version_id": result.get("version_id"),
        "version_no": result.get("version_no"),
        "status": str(result.get("status") or ""),
        "created_at": str(result.get("created_at") or ""),
    }


def sanitize_quote_export_result(result: dict, role: str = "sales") -> dict:
    """Return quote_export public fields only."""
    if not isinstance(result, dict):
        result = {}
    return {
        "quote_id": str(result.get("quote_id") or ""),
        "file_type": str(result.get("file_type") or ""),
        "file_path": str(result.get("file_path") or ""),
        "file_name": str(result.get("file_name") or ""),
        "created_at": str(result.get("created_at") or ""),
    }


def sanitize_quote_admin_result(result: dict, role: str = "sales") -> dict:
    """Return quote_admin public fields only."""
    if not isinstance(result, dict):
        result = {}
    out = {
        "action": str(result.get("action") or ""),
        "quote_id": str(result.get("quote_id") or ""),
        "quote_uid": str(result.get("quote_uid") or ""),
        "calc_quote_id": str(result.get("calc_quote_id") or ""),
        "version_id": result.get("version_id"),
        "version_no": result.get("version_no"),
        "status": str(result.get("status") or ""),
        "approval_status": str(result.get("approval_status") or result.get("status") or ""),
        "approval_note": str(result.get("approval_note") or ""),
        "updated_at": str(result.get("updated_at") or ""),
    }
    if "frozen" in result:
        out["frozen"] = bool(result.get("frozen"))
    if result.get("quote_summary") and isinstance(result.get("quote_summary"), dict):
        out["quote_summary"] = result["quote_summary"]
    return out


QUOTE_HISTORY_FIELDS = {
    "quote_uid",
    "latest_calc_quote_id",
    "product_name",
    "latest_version_no",
    "latest_saved_at",
    "approval_status",
    "sales_user_id",
    "sales_user_name",
    "material_total",
    "tier1_cost_before_margin",
    "has_admin_update",
    "admin_update_status",
}


def sanitize_quote_get_history_result(result: dict, role: str = "sales") -> dict:
    if not isinstance(result, dict):
        result = {}
    items = []
    raw_items = result.get("items")
    if isinstance(raw_items, list):
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            items.append({key: item.get(key) for key in QUOTE_HISTORY_FIELDS if key in item})
    return {
        "items": items,
        "limit": result.get("limit", 20),
        "offset": result.get("offset", 0),
        "count": len(items),
        "total": result.get("total", len(items)),
    }


DETAIL_ROW_FIELDS = {
    "line_no",
    "name",
    "spec",
    "usage",
    "unit_price",
    "amount",
    "amount_text",
    "source",
    "calc_note",
    "kb_hit",
}

FILE_FIELDS = {
    "file_id",
    "quote_uid",
    "calc_quote_id",
    "version_no",
    "original_name",
    "mime_type",
    "file_size",
    "uploaded_at",
    "file_role",
    "uploaded_by",
}


def sanitize_quote_get_detail_result(result: dict, role: str = "sales") -> dict:
    if not isinstance(result, dict):
        result = {}
    out = {
        "quote_uid": str(result.get("quote_uid") or ""),
        "version_id": result.get("version_id"),
        "calc_quote_id": str(result.get("calc_quote_id") or ""),
        "version_no": result.get("version_no"),
        "product_name": str(result.get("product_name") or ""),
        "approval_status": str(result.get("approval_status") or "pending"),
        "approval_note": str(result.get("approval_note") or ""),
        "validation_status": str(result.get("validation_status") or ""),
        "quote_mode": str(result.get("quote_mode") or ""),
        "structured_input": result.get("structured_input") if isinstance(result.get("structured_input"), dict) else {},
        "source_summary": result.get("source_summary") if isinstance(result.get("source_summary"), dict) else {},
        "sales_user_id": result.get("sales_user_id"),
        "sales_user_name": result.get("sales_user_name"),
        "detail_rows": [],
        "files": [],
        "admin_feedback": result.get("admin_feedback") if isinstance(result.get("admin_feedback"), dict) else {},
    }
    if isinstance(result.get("quote_result"), dict):
        out["quote_result"] = result["quote_result"]
    for row in result.get("detail_rows") if isinstance(result.get("detail_rows"), list) else []:
        if isinstance(row, dict):
            out["detail_rows"].append({key: row.get(key) for key in DETAIL_ROW_FIELDS if key in row})
    for file_info in result.get("files") if isinstance(result.get("files"), list) else []:
        if isinstance(file_info, dict):
            out["files"].append({key: file_info.get(key) for key in FILE_FIELDS if key in file_info})
    if result.get("include_chat_messages") and isinstance(result.get("chat_messages"), list):
        out["chat_messages"] = [
            {
                "message_id": str(msg.get("message_id") or ""),
                "role": str(msg.get("role") or ""),
                "created_at": str(msg.get("created_at") or ""),
            }
            for msg in result["chat_messages"]
            if isinstance(msg, dict)
        ]
    return out


PREFILL_META_FIELDS = {
    "co_name",
    "co_phone",
    "co_addr",
    "quote_no",
    "seller_contact",
    "seller_email",
    "cust_name",
    "cust_contact",
    "cust_phone",
    "cust_addr",
    "quote_date_iso",
    "sample_required",
    "sample_fee",
    "sample_lead_time",
    "payee_account_type",
    "payee_account_id",
    "payee_company_name",
}

PREFILL_ROW_FIELDS = {
    "line_order",
    "name",
    "size",
    "desc",
    "pack",
    "qty",
    "price",
    "total",
    "note",
    "taxed_price",
    "fob_price",
    "fob_price_usd",
    "fob_total",
    "fob_total_usd",
    "image_data_url",
}


def _sanitize_prefill(prefill: Any) -> dict:
    if not isinstance(prefill, dict):
        return {}
    meta = prefill.get("meta") if isinstance(prefill.get("meta"), dict) else {}
    rows = []
    raw_rows = prefill.get("rows")
    if isinstance(raw_rows, list):
        for row in raw_rows[:10]:
            if isinstance(row, dict):
                rows.append({key: row.get(key) for key in PREFILL_ROW_FIELDS if key in row})
    return {
        "quote_series_uid": str(prefill.get("quote_series_uid") or ""),
        "source": str(prefill.get("source") or "record"),
        "meta": {key: meta.get(key) for key in PREFILL_META_FIELDS if key in meta},
        "rows": rows,
        "suggested_export_lang": str(prefill.get("suggested_export_lang") or "cn"),
        "fob_quote": bool(prefill.get("fob_quote")),
        "product_name": str(prefill.get("product_name") or ""),
    }


def sanitize_quote_sheet_preview_result(result: dict, role: str = "sales") -> dict:
    if not isinstance(result, dict):
        result = {}
    summary = result.get("prefill_summary") if isinstance(result.get("prefill_summary"), dict) else {}
    out = {
        "quote_uid": str(result.get("quote_uid") or ""),
        "calc_quote_id": str(result.get("calc_quote_id") or ""),
        "version_id": result.get("version_id"),
        "version_no": result.get("version_no"),
        "product_name": str(result.get("product_name") or ""),
        "approval_status": str(result.get("approval_status") or "pending"),
        "preview_url": str(result.get("preview_url") or ""),
        "prefill_available": bool(result.get("prefill_available")),
        "prefill_summary": {
            "quote_no": str(summary.get("quote_no") or ""),
            "customer_name": str(summary.get("customer_name") or ""),
            "product_name": str(summary.get("product_name") or ""),
            "rows_count": int(summary.get("rows_count") or 0),
            "has_images": bool(summary.get("has_images")),
            "suggested_export_lang": str(summary.get("suggested_export_lang") or "cn"),
            "fob_quote": bool(summary.get("fob_quote")),
            "needs_user_completion": summary.get("needs_user_completion")
            if isinstance(summary.get("needs_user_completion"), list)
            else [],
        },
    }
    if result.get("prefill") is not None:
        out["prefill"] = _sanitize_prefill(result.get("prefill"))
    return out


def _sanitize_prefill_summary(summary: Any) -> dict:
    summary = summary if isinstance(summary, dict) else {}
    return {
        "quote_no": str(summary.get("quote_no") or ""),
        "customer_name": str(summary.get("customer_name") or ""),
        "product_name": str(summary.get("product_name") or ""),
        "rows_count": int(summary.get("rows_count") or 0),
        "has_images": bool(summary.get("has_images")),
        "suggested_export_lang": str(summary.get("suggested_export_lang") or "cn"),
        "fob_quote": bool(summary.get("fob_quote")),
        "needs_user_completion": summary.get("needs_user_completion")
        if isinstance(summary.get("needs_user_completion"), list)
        else [],
    }


def sanitize_quote_export_pdf_result(result: dict, role: str = "sales") -> dict:
    if not isinstance(result, dict):
        result = {}
    out = {
        "quote_uid": str(result.get("quote_uid") or ""),
        "calc_quote_id": str(result.get("calc_quote_id") or ""),
        "version_id": result.get("version_id"),
        "version_no": result.get("version_no"),
        "approval_status": str(result.get("approval_status") or "pending"),
        "approval_note": str(result.get("approval_note") or ""),
        "export_lang": str(result.get("export_lang") or "cn"),
        "currency_mode": str(result.get("currency_mode") or "rmb"),
        "prefill_summary": _sanitize_prefill_summary(result.get("prefill_summary")),
    }
    if result.get("dry_run"):
        out.update(
            {
                "dry_run": True,
                "can_export": bool(result.get("can_export")),
                "missing_fields": result.get("missing_fields")
                if isinstance(result.get("missing_fields"), list)
                else [],
            }
        )
        return out
    out.update(
        {
            "file_name": str(result.get("file_name") or ""),
            "file_path": str(result.get("file_path") or ""),
            "download_url": str(result.get("download_url") or ""),
            "file_size": int(result.get("file_size") or 0),
            "export_status": str(result.get("export_status") or ""),
        }
    )
    return out


def sanitize_quote_approval_status_result(result: dict, role: str = "sales") -> dict:
    if not isinstance(result, dict):
        result = {}
    quote_summary = result.get("quote_summary") if isinstance(result.get("quote_summary"), dict) else {}
    out = {
        "quote_uid": str(result.get("quote_uid") or ""),
        "calc_quote_id": str(result.get("calc_quote_id") or ""),
        "version_id": result.get("version_id"),
        "version_no": result.get("version_no"),
        "approval_status": str(result.get("approval_status") or "pending"),
        "approval_note": str(result.get("approval_note") or ""),
        "approval_updated_at": str(result.get("approval_updated_at") or ""),
        "approved_by": str(result.get("approved_by") or ""),
        "quote_summary": {
            "product_name": str(quote_summary.get("product_name") or ""),
            "tier_count": int(quote_summary.get("tier_count") or 0),
            "material_total": quote_summary.get("material_total"),
        },
    }
    feedback = result.get("admin_feedback")
    if isinstance(feedback, dict):
        out["admin_feedback"] = {
            "has_feedback": bool(feedback.get("has_feedback")),
            "feedback_type": str(feedback.get("feedback_type") or "none"),
            "summary": str(feedback.get("summary") or ""),
            "has_admin_corrected_quote": bool(feedback.get("has_admin_corrected_quote")),
            "admin_corrected_at": str(feedback.get("admin_corrected_at") or ""),
        }
    readiness = result.get("export_readiness")
    if isinstance(readiness, dict):
        out["export_readiness"] = {
            "can_export": bool(readiness.get("can_export")),
            "reason": str(readiness.get("reason") or ""),
            "next_action_hint": str(readiness.get("next_action_hint") or ""),
        }
    return out
