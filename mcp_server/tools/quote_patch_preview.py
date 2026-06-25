from __future__ import annotations

import copy
from typing import Any

from mcp_server.audit import write_audit_log
from mcp_server.auth import require_tool_permission
from mcp_server.sanitizer import sanitize_quote_patch_preview_result
from mcp_server.schemas import normalize_user_context, validate_quote_patch_preview_input


TOOL_NAME = "quote_patch_preview"
MODE = "readonly"

SUPPORTED_PATCH_FIELDS = {
    "quantity",
    "processing_fee",
    "processing_fee_delta",
    "material_replace",
}


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round_money(value: float | int | None) -> float:
    return round(float(value or 0), 2)


def _tiers(quote: dict[str, Any]) -> list[dict[str, Any]]:
    tiers = quote.get("tiers")
    return tiers if isinstance(tiers, list) else []


def _primary_total(quote: dict[str, Any]) -> float:
    selected = quote.get("selected_tier")
    if isinstance(selected, dict):
        for key in ("exw_price", "fob_price", "total_price", "total"):
            val = _number(selected.get(key))
            if val is not None:
                return _round_money(val)
    tiers = _tiers(quote)
    for tier in tiers:
        if isinstance(tier, dict):
            for key in ("exw_price", "fob_price", "total_price", "total"):
                val = _number(tier.get(key))
                if val is not None:
                    return _round_money(val)
    return 0.0


def _apply_quantity_patch(patched: dict[str, Any], quantity: Any, changed_fields: list[str]) -> None:
    target = _number(quantity)
    if target is None:
        return
    patched["preview_quantity"] = int(target) if target.is_integer() else target
    for tier in _tiers(patched):
        if not isinstance(tier, dict):
            continue
        tier_quantity = _number(tier.get("quantity"))
        if tier_quantity == target:
            patched["selected_tier"] = copy.deepcopy(tier)
            break
    changed_fields.append("quantity")


def _apply_processing_fee_patch(
    patched: dict[str, Any],
    patch: dict[str, Any],
    changed_fields: list[str],
) -> None:
    if "processing_fee" not in patch and "processing_fee_delta" not in patch:
        return

    explicit_fee = _number(patch.get("processing_fee")) if "processing_fee" in patch else None
    fee_delta = _number(patch.get("processing_fee_delta")) if "processing_fee_delta" in patch else None
    if explicit_fee is None and fee_delta is None:
        return

    for tier in _tiers(patched):
        if not isinstance(tier, dict):
            continue
        old_fee = _number(tier.get("processing_fee"))
        if old_fee is None:
            old_fee = 0.0
        new_fee = explicit_fee if explicit_fee is not None else old_fee + float(fee_delta or 0)
        delta = new_fee - old_fee
        tier["processing_fee"] = _round_money(new_fee)
        for key in ("cost_before_margin", "unit_cost", "exw_price", "fob_price", "total_price", "total"):
            current = _number(tier.get(key))
            if current is not None:
                tier[key] = _round_money(current + delta)

    if isinstance(patched.get("selected_tier"), dict):
        selected_quantity = patched["selected_tier"].get("quantity")
        for tier in _tiers(patched):
            if isinstance(tier, dict) and tier.get("quantity") == selected_quantity:
                patched["selected_tier"] = copy.deepcopy(tier)
                break
    changed_fields.append("processing_fee")


def _apply_material_replace(patched: dict[str, Any], material_replace: Any, changed_fields: list[str]) -> None:
    replacement = str(material_replace or "").strip()
    if not replacement:
        return
    items = patched.get("items")
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                item["preview_material_replace"] = replacement
    patched["preview_material_replace"] = replacement
    changed_fields.append("material_replace")


def _build_diff(
    original: dict[str, Any],
    patched: dict[str, Any],
    changed_fields: list[str],
    unsupported_fields: list[str],
) -> dict[str, Any]:
    before_total = _primary_total(original)
    after_total = _primary_total(patched)
    delta = _round_money(after_total - before_total)
    delta_percent = round((delta / before_total * 100), 2) if before_total else 0
    return {
        "changed_fields": changed_fields,
        "before_total": before_total,
        "after_total": after_total,
        "delta": delta,
        "delta_percent": delta_percent,
        "unsupported_fields": unsupported_fields,
    }


def _preview_quote_patch(quote_result: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    original = copy.deepcopy(quote_result)
    patched = copy.deepcopy(quote_result)
    changed_fields: list[str] = []
    unsupported_fields = [key for key in patch if key not in SUPPORTED_PATCH_FIELDS]

    if not patch:
        return {
            "original_quote": original,
            "patched_quote": patched,
            "diff": _build_diff(original, patched, [], []),
        }

    if "quantity" in patch:
        _apply_quantity_patch(patched, patch.get("quantity"), changed_fields)
    if "processing_fee" in patch or "processing_fee_delta" in patch:
        _apply_processing_fee_patch(patched, patch, changed_fields)
    if "material_replace" in patch:
        _apply_material_replace(patched, patch.get("material_replace"), changed_fields)

    return {
        "original_quote": original,
        "patched_quote": patched,
        "diff": _build_diff(original, patched, changed_fields, unsupported_fields),
    }


def _audit_record(
    user_context: dict[str, Any],
    patch: Any,
    success: bool,
    error: str | None = None,
) -> dict[str, Any]:
    patch_keys = sorted(patch.keys()) if isinstance(patch, dict) else []
    return {
        "tool": TOOL_NAME,
        "user_id": user_context.get("user_id"),
        "role": user_context.get("role", "guest"),
        "session_id": user_context.get("session_id"),
        "patch_keys": patch_keys,
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


def quote_patch_preview(input_data: dict) -> dict:
    user_context = normalize_user_context(
        input_data.get("user_context") if isinstance(input_data, dict) else {}
    )
    patch = {}

    try:
        require_tool_permission(user_context, TOOL_NAME)
        user_context, query = validate_quote_patch_preview_input(input_data)
        quote_result = query["quote_result"]
        patch = query["patch"]

        result = _preview_quote_patch(quote_result, patch)
        sanitized = sanitize_quote_patch_preview_result(result, user_context.get("role", "sales"))
        write_audit_log(_audit_record(user_context, patch, success=True))
        return {
            "ok": True,
            "tool": TOOL_NAME,
            "mode": MODE,
            "result": sanitized,
        }
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
        try:
            write_audit_log(_audit_record(user_context, patch, success=False, error=error))
        except Exception:
            pass
        return _failure(error)
