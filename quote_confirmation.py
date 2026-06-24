"""报价前确认层：区分 system/manual/final 值，报价计算只消费 final_value。"""
from __future__ import annotations

import copy
import re
from typing import Any

from material_row_validity import (
    row_exclusion_reasons_for_quote,
    row_has_valid_unit_price_for_quote,
    row_is_quotable_for_cost,
)
from price_source_resolver import (
    PRICE_SOURCE_AI,
    PRICE_SOURCE_KB,
    PRICE_SOURCE_MANUAL,
    PRICE_SOURCE_OVERRIDE,
    PRICE_SOURCE_SHEET,
    infer_price_source,
)

SOURCE_MANUAL = "manual"
SOURCE_ADMIN = "admin"
SOURCE_KB = "knowledge_base"
SOURCE_STRUCTURE = "structure_derived"
SOURCE_SHEET = "sheet"
SOURCE_AI = "ai_extract"
SOURCE_MISSING = "missing"
SOURCE_NON_AREA = "non_area_piece"

STATUS_CONFIRMED = "confirmed"
STATUS_PENDING = "pending"
STATUS_EXCLUDED = "excluded"
STATUS_CONFLICT = "conflict"


def _confirmed_field(
    *,
    system_value: Any = None,
    manual_value: Any = None,
    final_value: Any = None,
    source: str = SOURCE_MISSING,
) -> dict[str, Any]:
    return {
        "system_value": system_value,
        "manual_value": manual_value,
        "final_value": final_value,
        "source": source,
    }


def _is_missing_price(text: object) -> bool:
    val = str(text or "").strip()
    return not val or val in {"-", "—", "/"}


def _parse_manual_number(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text in {"-", "—"}:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)", text.replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _map_price_source(row: dict[str, Any]) -> str:
    ps = infer_price_source(row)
    if ps == PRICE_SOURCE_MANUAL:
        return SOURCE_MANUAL
    if ps == PRICE_SOURCE_OVERRIDE:
        return SOURCE_ADMIN
    if ps == PRICE_SOURCE_KB:
        return SOURCE_KB
    if ps == PRICE_SOURCE_AI:
        return SOURCE_AI
    if ps == PRICE_SOURCE_SHEET:
        return SOURCE_SHEET
    if bool(row.get("unit_price_ai")):
        return SOURCE_AI
    if bool(row.get("kb_hit")):
        return SOURCE_KB
    if str(row.get("confirmation_source") or "").strip() in {"admin_edit", "admin"}:
        return SOURCE_ADMIN
    return SOURCE_SHEET


def _summary_index(summaries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for summary in summaries:
        if not isinstance(summary, dict):
            continue
        for key in (
            str(summary.get("material_name") or "").strip(),
            str(summary.get("material_code") or "").strip(),
        ):
            if key and key not in out:
                out[key] = summary
    return out


def _usage_from_summary(summary: dict[str, Any] | None) -> tuple[Any, str | None]:
    if not isinstance(summary, dict):
        return None, None
    ms = summary.get("measure_summary") if isinstance(summary.get("measure_summary"), dict) else {}
    kind = str(summary.get("material_measure_kind") or "")
    if kind == "count_with_length":
        qty = ms.get("quantity")
        unit = str(ms.get("measure_unit") or "条").strip() or "条"
        if qty is not None:
            return qty, unit
    if kind == "count":
        qty = ms.get("quantity")
        unit = str(ms.get("measure_unit") or "个").strip() or "个"
        if qty is not None:
            return qty, unit
    if summary.get("total_area_m2") is not None:
        return summary.get("total_area_m2"), "㎡"
    if summary.get("total_area_cm2") is not None:
        return round(float(summary["total_area_cm2"]) / 10_000.0, 4), "㎡"
    return None, None


def _resolve_field(
    *,
    system_value: Any,
    manual_value: Any,
    default_source: str,
    missing_checker=None,
) -> dict[str, Any]:
    checker = missing_checker or (lambda v: v is None or str(v).strip() in {"", "-", "—"})
    if manual_value is not None and not checker(manual_value):
        return _confirmed_field(
            system_value=system_value,
            manual_value=manual_value,
            final_value=manual_value,
            source=SOURCE_MANUAL,
        )
    if not checker(system_value):
        return _confirmed_field(
            system_value=system_value,
            manual_value=None,
            final_value=system_value,
            source=default_source,
        )
    return _confirmed_field(
        system_value=system_value,
        manual_value=None,
        final_value=None,
        source=SOURCE_MISSING,
    )


def _row_status(
    *,
    included: bool,
    unit_price_field: dict[str, Any],
    usage_field: dict[str, Any],
    row: dict[str, Any],
) -> str:
    if bool(row.get("price_conflict_required")):
        return STATUS_CONFLICT
    if unit_price_field.get("source") == SOURCE_MISSING or usage_field.get("source") == SOURCE_MISSING:
        return STATUS_PENDING
    if not included:
        return STATUS_EXCLUDED
    reasons = row_exclusion_reasons_for_quote(row)
    if reasons and any(r in {"缺少单价", "缺少用量"} for r in reasons):
        return STATUS_PENDING
    return STATUS_CONFIRMED


def build_material_confirmation_row(
    row: dict[str, Any],
    *,
    row_id: str,
    summary: dict[str, Any] | None = None,
    manual_patch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    patch = manual_patch if isinstance(manual_patch, dict) else {}
    name = str(row.get("name") or "").strip()
    system_price = None if _is_missing_price(row.get("unit_price")) else str(row.get("unit_price") or "").strip()
    system_usage = str(row.get("usage") or "").strip() or None
    if system_usage in {"-", "—"}:
        system_usage = None

    struct_usage, struct_unit = _usage_from_summary(summary)
    usage_source = _map_price_source(row)
    if struct_usage is not None and (not system_usage or usage_source in {SOURCE_AI, SOURCE_MISSING}):
        system_usage = struct_usage
        usage_source = SOURCE_STRUCTURE

    manual_name = patch.get("material_name")
    if isinstance(manual_name, dict):
        manual_name = manual_name.get("manual_value")
    manual_price = patch.get("unit_price")
    if isinstance(manual_price, dict):
        manual_price = manual_price.get("manual_value")
    manual_usage = patch.get("usage") if "usage" in patch else patch.get("quantity")
    if isinstance(manual_usage, dict):
        manual_usage = manual_usage.get("manual_value")
    manual_unit = patch.get("measure_unit")
    if isinstance(manual_unit, dict):
        manual_unit = manual_unit.get("manual_value")

    name_field = _resolve_field(
        system_value=name,
        manual_value=str(manual_name).strip() if manual_name not in (None, "") else None,
        default_source=SOURCE_SHEET,
    )
    price_field = _resolve_field(
        system_value=system_price,
        manual_value=str(manual_price).strip() if manual_price not in (None, "") else manual_price,
        default_source=_map_price_source(row),
        missing_checker=_is_missing_price,
    )
    usage_field = _resolve_field(
        system_value=system_usage,
        manual_value=manual_usage,
        default_source=usage_source,
        missing_checker=lambda v: v is None or str(v).strip() in {"", "-", "—"},
    )

    measure_unit = struct_unit or _infer_measure_unit(row, summary)
    unit_field = _resolve_field(
        system_value=measure_unit,
        manual_value=str(manual_unit).strip() if manual_unit not in (None, "") else None,
        default_source=usage_source if struct_unit else SOURCE_SHEET,
    )

    default_included = row_is_quotable_for_cost(row)
    if (
        not default_included
        and usage_field.get("final_value") is not None
        and not _is_missing_price(price_field.get("final_value"))
    ):
        probe = dict(row)
        probe["usage"] = _format_usage(
            usage_field.get("final_value"),
            unit_field.get("final_value") if isinstance(unit_field.get("final_value"), str) else None,
        )
        probe["unit_price"] = str(price_field.get("final_value") or "").strip()
        default_included = row_is_quotable_for_cost(probe)
    if patch.get("included_in_quote") is False:
        included = False
    elif patch.get("included_in_quote") is True:
        included = True
    else:
        included = default_included and price_field.get("final_value") is not None

    notes: list[str] = []
    if isinstance(patch.get("notes"), list):
        notes = [str(n).strip() for n in patch["notes"] if str(n).strip()]
    elif patch.get("notes"):
        notes = [str(patch.get("notes")).strip()]

    status = _row_status(
        included=included,
        unit_price_field=price_field,
        usage_field=usage_field,
        row=row,
    )
    if patch.get("status") in {STATUS_CONFIRMED, STATUS_PENDING, STATUS_EXCLUDED, STATUS_CONFLICT}:
        status = str(patch["status"])

    return {
        "row_id": row_id,
        "index": row.get("_quote_row_index"),
        "material_name": name_field,
        "unit_price": price_field,
        "usage": usage_field,
        "quantity": usage_field,
        "measure_unit": unit_field,
        "included_in_quote": included,
        "status": status,
        "notes": notes,
        "recognition_status": str(row.get("recognition_status") or "").strip(),
        "price_source_system": _map_price_source(row),
        "exclusion_reasons": row_exclusion_reasons_for_quote(row),
    }


def _infer_measure_unit(row: dict[str, Any], summary: dict[str, Any] | None) -> str | None:
    if isinstance(summary, dict):
        ms = summary.get("measure_summary") if isinstance(summary.get("measure_summary"), dict) else {}
        unit = str(ms.get("measure_unit") or "").strip()
        if unit:
            return unit
        kind = str(summary.get("material_measure_kind") or "")
        if kind.endswith("_area"):
            return "㎡"
    usage = str(row.get("usage") or "").strip()
    if usage.endswith("㎡") or "㎡" in usage or usage.endswith("m2"):
        return "㎡"
    if usage.endswith("码"):
        return "码"
    if usage.endswith("条"):
        return "条"
    if usage.endswith("个"):
        return "个"
    price = str(row.get("unit_price") or "")
    if "元/㎡" in price or "元/m2" in price.lower():
        return "㎡"
    if "元/码" in price:
        return "码"
    if "元/条" in price:
        return "条"
    if "元/个" in price:
        return "个"
    return None


def build_quote_confirmation(
    payload: dict[str, Any],
    *,
    material_summaries: list[dict[str, Any]] | None = None,
    manual_materials: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    summaries = material_summaries if isinstance(material_summaries, list) else []
    summary_by_name = _summary_index(summaries)
    manual_by_id = {
        str(m.get("row_id") or ""): m
        for m in (manual_materials or [])
        if isinstance(m, dict) and str(m.get("row_id") or "").strip()
    }
    materials: list[dict[str, Any]] = []
    pending_fields: list[str] = []
    for idx, row in enumerate(items):
        if not isinstance(row, dict) or bool(row.get("deleted")):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        row_id = str(row.get("quote_row_id") or row.get("row_id") or f"material_{idx + 1}")
        row_copy = dict(row)
        row_copy["_quote_row_index"] = idx
        mat_row = build_material_confirmation_row(
            row_copy,
            row_id=row_id,
            summary=summary_by_name.get(name),
            manual_patch=manual_by_id.get(row_id),
        )
        materials.append(mat_row)
        if mat_row["status"] == STATUS_PENDING:
            if mat_row["unit_price"].get("final_value") is None:
                pending_fields.append(f"{name}:unit_price")
            if mat_row["usage"].get("final_value") is None:
                pending_fields.append(f"{name}:usage")
        if mat_row["status"] == STATUS_CONFLICT:
            pending_fields.append(f"{name}:price_conflict")

    return {
        "materials": materials,
        "pending_fields": pending_fields,
        "requires_confirmation": bool(materials),
        "has_blocking_pending": any(m["status"] in {STATUS_PENDING, STATUS_CONFLICT} for m in materials),
    }


def merge_quote_confirmation_overrides(
    confirmation: dict[str, Any],
    overrides: dict[str, Any] | None,
) -> dict[str, Any]:
    base = copy.deepcopy(confirmation) if isinstance(confirmation, dict) else {"materials": [], "pending_fields": []}
    if not isinstance(overrides, dict):
        return base
    override_materials = overrides.get("materials")
    if not isinstance(override_materials, list):
        return base
    by_id = {
        str(m.get("row_id") or ""): m
        for m in override_materials
        if isinstance(m, dict) and str(m.get("row_id") or "").strip()
    }
    merged_materials: list[dict[str, Any]] = []
    for mat in base.get("materials") or []:
        if not isinstance(mat, dict):
            continue
        row_id = str(mat.get("row_id") or "")
        patch = by_id.get(row_id) or {}
        merged = copy.deepcopy(mat)
        for key in ("material_name", "unit_price", "usage", "quantity", "measure_unit"):
            if key not in patch:
                continue
            patch_val = patch[key]
            if isinstance(patch_val, dict):
                field = merged.get(key) if isinstance(merged.get(key), dict) else _confirmed_field()
                if "manual_value" in patch_val:
                    field["manual_value"] = patch_val["manual_value"]
                if patch_val.get("manual_value") is not None:
                    field["final_value"] = patch_val.get("manual_value")
                    field["source"] = SOURCE_MANUAL
                merged[key] = field
            else:
                field = merged.get(key) if isinstance(merged.get(key), dict) else _confirmed_field()
                field["manual_value"] = patch_val
                field["final_value"] = patch_val
                field["source"] = SOURCE_MANUAL
                merged[key] = field
        if "included_in_quote" in patch:
            merged["included_in_quote"] = bool(patch["included_in_quote"])
        if patch.get("notes"):
            merged["notes"] = patch["notes"] if isinstance(patch["notes"], list) else [str(patch["notes"])]
        if patch.get("status"):
            merged["status"] = patch["status"]
        merged_materials.append(merged)
    base["materials"] = [recompute_confirmation_material(m) for m in merged_materials if isinstance(m, dict)]
    base["pending_fields"] = [
        f"{m.get('material_name', {}).get('final_value') or m.get('row_id')}:unit_price"
        for m in merged_materials
        if isinstance(m, dict)
        and m.get("included_in_quote")
        and isinstance(m.get("unit_price"), dict)
        and m["unit_price"].get("final_value") is None
    ]
    base["has_blocking_pending"] = any(
        m.get("status") in {STATUS_PENDING, STATUS_CONFLICT} and m.get("included_in_quote")
        for m in merged_materials
        if isinstance(m, dict)
    )
    return base


def _format_usage(final_usage: Any, measure_unit: str | None) -> str:
    if final_usage is None:
        return "-"
    if isinstance(final_usage, str):
        text = final_usage.strip()
        if text:
            return text
    unit = str(measure_unit or "").strip()
    if unit == "㎡":
        try:
            num = float(final_usage)
            return f"{num:g}㎡"
        except (TypeError, ValueError):
            pass
    if unit:
        return f"{final_usage}{unit}"
    return str(final_usage)


def _refresh_row_amount_after_confirmation(
    row: dict[str, Any],
    *,
    old_unit_price: str,
) -> None:
    """确认层写回单价/用量后，按 final 值重算小计，清除 stale amount。"""
    from material_spec_usage_enricher import usage_for_amount_recalc
    from quote_engine import _recalculated_amount_and_price, reconcile_row_amount_after_unit_price_change

    usage_raw = str(usage_for_amount_recalc(row) or row.get("usage") or "").strip()
    unit_price = str(row.get("unit_price") or "").strip()
    recalculated = _recalculated_amount_and_price(usage_raw, unit_price)
    if recalculated is not None:
        row["amount"] = recalculated[0]
        row["amount_ai"] = False
        row.pop("amount_text", None)
        return
    reconcile_row_amount_after_unit_price_change(
        row,
        old_unit_text=old_unit_price,
    )
    row.pop("amount_text", None)
    row["amount_ai"] = False


def apply_quote_confirmation_to_items(
    items: list[dict[str, Any]],
    confirmation: dict[str, Any],
) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    mats = confirmation.get("materials") if isinstance(confirmation, dict) else None
    if not isinstance(mats, list):
        return items
    by_index: dict[int, dict[str, Any]] = {}
    by_id: dict[str, dict[str, Any]] = {}
    for mat in mats:
        if not isinstance(mat, dict):
            continue
        row_id = str(mat.get("row_id") or "")
        if row_id:
            by_id[row_id] = mat
        idx = mat.get("index")
        if isinstance(idx, int):
            by_index[idx] = mat

    out: list[dict[str, Any]] = []
    for idx, raw in enumerate(items):
        if not isinstance(raw, dict):
            out.append(raw)
            continue
        row = dict(raw)
        row_id = str(row.get("quote_row_id") or row.get("row_id") or f"material_{idx + 1}")
        old_unit_price = str(row.get("unit_price") or "").strip()
        mat = by_index.get(idx) or by_id.get(row_id)
        if not isinstance(mat, dict):
            out.append(row)
            continue

        name_field = mat.get("material_name") if isinstance(mat.get("material_name"), dict) else {}
        price_field = mat.get("unit_price") if isinstance(mat.get("unit_price"), dict) else {}
        usage_field = mat.get("usage") if isinstance(mat.get("usage"), dict) else {}
        unit_field = mat.get("measure_unit") if isinstance(mat.get("measure_unit"), dict) else {}

        final_name = name_field.get("final_value")
        if final_name not in (None, ""):
            row["name"] = str(final_name).strip()

        final_price = price_field.get("final_value")
        price_source = str(price_field.get("source") or SOURCE_MISSING)
        if final_price not in (None, ""):
            row["unit_price"] = str(final_price).strip()
            if price_source == SOURCE_MANUAL:
                row["price_source"] = "manual"
                row["confirmation_source"] = "quote_confirmed_manual"
            elif price_source == SOURCE_ADMIN:
                row["price_source"] = "override"
                row["override_hit"] = True
                row["confirmation_source"] = "admin"
            elif price_source == SOURCE_KB:
                row["price_source"] = "kb"
            elif price_source == SOURCE_AI:
                row["price_source"] = "ai_estimate"
            else:
                row["price_source"] = "sheet"
            row["unit_price_ai"] = price_source == SOURCE_AI
            row["kb_hit"] = price_source == SOURCE_KB

        measure_unit = unit_field.get("final_value")
        final_usage = usage_field.get("final_value")
        if final_usage is not None:
            row["usage"] = _format_usage(final_usage, measure_unit if isinstance(measure_unit, str) else None)
            row["usage_ai"] = str(usage_field.get("source") or "") == SOURCE_STRUCTURE

        included = bool(mat.get("included_in_quote"))
        row["exclude_from_cost"] = not included
        row["amount_in_cost"] = included
        if included and not _is_missing_price(row.get("unit_price")):
            _refresh_row_amount_after_confirmation(row, old_unit_price=old_unit_price)
        elif not included:
            row["amount"] = 0.0
            row.pop("amount_text", None)
            row["amount_ai"] = False
        row["quote_confirmation_status"] = mat.get("status")
        row["quote_confirmation_applied"] = True
        if isinstance(mat.get("notes"), list) and mat["notes"]:
            row["quote_confirmation_notes"] = mat["notes"]
        out.append(row)
    return out


def build_quote_confirmation_payload(
    payload: dict[str, Any],
    *,
    material_summaries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    confirmation = build_quote_confirmation(payload, material_summaries=material_summaries)
    pending_n = sum(1 for m in confirmation.get("materials") or [] if m.get("status") == STATUS_PENDING)
    conflict_n = sum(1 for m in confirmation.get("materials") or [] if m.get("status") == STATUS_CONFLICT)
    risks: list[str] = []
    if pending_n:
        risks.append(f"{pending_n} 行关键字段待确认（单价/用量）")
    if conflict_n:
        risks.append(f"{conflict_n} 行单价存在冲突")
    ai_rows = sum(
        1
        for m in confirmation.get("materials") or []
        if isinstance(m, dict)
        and str(m.get("price_source_system") or "") == SOURCE_AI
    )
    if ai_rows:
        risks.append(f"{ai_rows} 行单价为系统估算，请核对后确认")

    return {
        "quote_ready": False,
        "reply_type": "quote_confirmation",
        "intent": "QUOTE_CONFIRMATION_REQUIRED",
        "assistant_message": (
            "已完成数据识别与知识库匹配，请核对并确认最终单价/用量后再生成正式报价。"
            "系统识别值仅供参考，确认后才会参与计价。"
        ),
        "title": "报价前确认",
        "quote_confirmation": confirmation,
        "confirmation_risks": risks,
        "items_preview": payload.get("items") if isinstance(payload.get("items"), list) else [],
    }


def should_require_quote_confirmation(payload: dict[str, Any]) -> bool:
    if bool(payload.get("quote_confirmed")):
        return False
    if bool(payload.get("skip_quote_confirmation")):
        return False
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    active = [r for r in items if isinstance(r, dict) and not bool(r.get("deleted"))]
    if not active:
        return False
    if bool(payload.get("structure_confirmed")):
        return True
    if bool(payload.get("require_quote_confirmation")):
        return True
    return False


def recompute_confirmation_material(mat: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(mat, dict):
        return mat
    included = bool(mat.get("included_in_quote"))
    price_field = mat.get("unit_price") if isinstance(mat.get("unit_price"), dict) else {}
    usage_field = mat.get("usage") if isinstance(mat.get("usage"), dict) else {}
    out = dict(mat)
    if included:
        if _is_missing_price(price_field.get("final_value")):
            out["status"] = STATUS_PENDING
        elif usage_field.get("final_value") is None or str(usage_field.get("final_value")).strip() in {"", "-", "—"}:
            out["status"] = STATUS_PENDING
        elif out.get("status") != STATUS_CONFLICT:
            out["status"] = STATUS_CONFIRMED
    else:
        out["status"] = STATUS_EXCLUDED
    return out


def validate_quote_confirmation_for_calc(
    confirmation: dict[str, Any],
) -> tuple[bool, str, dict[str, Any]]:
    conf = copy.deepcopy(confirmation) if isinstance(confirmation, dict) else {"materials": []}
    materials = [
        recompute_confirmation_material(m)
        for m in (conf.get("materials") or [])
        if isinstance(m, dict)
    ]
    conf["materials"] = materials
    included = [m for m in materials if m.get("included_in_quote")]
    if not included:
        conf["has_blocking_pending"] = True
        return False, "没有勾选参与报价的材料，请至少保留一行有效材料后再生成正式报价。", conf

    blocking: list[str] = []
    for m in included:
        name = str(m.get("material_name", {}).get("final_value") or m.get("row_id") or "材料")
        pf = m.get("unit_price") if isinstance(m.get("unit_price"), dict) else {}
        uf = m.get("usage") if isinstance(m.get("usage"), dict) else {}
        if _is_missing_price(pf.get("final_value")):
            blocking.append(f"{name}（缺少单价）")
        elif uf.get("final_value") is None or str(uf.get("final_value")).strip() in {"", "-", "—"}:
            blocking.append(f"{name}（缺少用量）")
        elif m.get("status") == STATUS_CONFLICT:
            blocking.append(f"{name}（单价冲突）")
        else:
            from badge_unit_guard import badge_accessory_unit_conflict_hints

            probe = {
                "name": name,
                "usage": uf.get("final_value"),
                "unit_price": pf.get("final_value"),
            }
            badge_hints = badge_accessory_unit_conflict_hints(probe)
            if badge_hints:
                blocking.append(f"{name}（{badge_hints[0]}）")
    if blocking:
        conf["has_blocking_pending"] = True
        conf["pending_fields"] = blocking
        preview = "、".join(blocking[:5])
        suffix = f" 等 {len(blocking)} 项" if len(blocking) > 5 else ""
        return (
            False,
            f"仍有参与报价的材料未完成确认：{preview}{suffix}。请补全单价/用量后再生成正式报价。",
            conf,
        )

    conf["has_blocking_pending"] = False
    conf["pending_fields"] = []
    return True, "", conf
