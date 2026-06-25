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
        "quote_id": str(result.get("quote_id") or ""),
        "status": str(result.get("status") or ""),
        "locked": bool(result.get("locked")),
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
        "status": str(result.get("status") or ""),
        "updated_at": str(result.get("updated_at") or ""),
    }
    if "frozen" in result:
        out["frozen"] = bool(result.get("frozen"))
    if result.get("quote_summary") and isinstance(result.get("quote_summary"), dict):
        out["quote_summary"] = result["quote_summary"]
    return out
