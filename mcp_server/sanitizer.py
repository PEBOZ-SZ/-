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
