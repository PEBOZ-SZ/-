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
