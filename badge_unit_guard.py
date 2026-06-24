"""配件类标牌/拉牌材料：禁止误按「码」计价，优先按个/只/套。"""
from __future__ import annotations

import re
from typing import Any

from material_piece_summary import _is_count_badge_material

BADGE_UNIT_CONFLICT_REASON = (
    "配件类材料应按个/只/套计量；当前为码用量或码单价，请补充数量（如1个）与个价（如x元/个）"
)

_PIECE_PRICE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*元?\s*(?:/|每)\s*(?:个|只|套|件|pcs|pc|PCS|对)",
    re.I,
)
_PIECE_QTY_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(?:个|只|套|件|pcs|pc|PCS|对)",
    re.I,
)
_SPEC_ONLY_RE = re.compile(r"^#?\d+(?:#\d+)?(?:号)?$", re.I)


def is_count_badge_accessory(name: str, mat_type: str = "", remark: str = "") -> bool:
    return _is_count_badge_material(str(name or "").strip(), str(mat_type or "").strip(), str(remark or "").strip())


def _first_number(text: Any) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)", str(text or "").replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group(1))
    except (TypeError, ValueError):
        return None


def _unit_kind(text: Any, *, price: bool) -> str:
    from quote_engine import _price_unit_kind, _usage_unit_kind

    return _price_unit_kind(text) if price else _usage_unit_kind(text)


def is_yard_unit_text(text: Any) -> bool:
    kind = _unit_kind(text, price=False)
    return kind == "yard"


def is_piece_unit_text(text: Any) -> bool:
    return _unit_kind(text, price=False) == "piece" or _unit_kind(text, price=True) == "piece"


def badge_accessory_uses_yard_units(row: dict[str, Any]) -> bool:
    usage = str(row.get("usage") or "").strip()
    unit_price = str(row.get("unit_price") or "").strip()
    return is_yard_unit_text(usage) or is_yard_unit_text(unit_price)


def badge_accessory_uses_piece_units(row: dict[str, Any]) -> bool:
    usage = str(row.get("usage") or "").strip()
    unit_price = str(row.get("unit_price") or "").strip()
    usage_piece = _unit_kind(usage, price=False) == "piece"
    price_piece = _unit_kind(unit_price, price=True) == "piece"
    return usage_piece and price_piece


def _extract_piece_price_from_text(text: Any) -> float | None:
    raw = str(text or "").strip()
    if not raw or raw in {"-", "—"}:
        return None
    match = _PIECE_PRICE_RE.search(raw)
    if match:
        return _first_number(match.group(1))
    if _unit_kind(raw, price=True) == "piece":
        return _first_number(raw)
    return None


def _extract_piece_quantity_from_text(text: Any, *, default: int | None = None) -> int | None:
    raw = str(text or "").strip()
    if not raw or raw in {"-", "—"}:
        return default
    match = _PIECE_QTY_RE.search(raw)
    if match:
        return max(1, int(round(float(match.group(1)))))
    if _unit_kind(raw, price=False) == "piece" and not _PIECE_PRICE_RE.search(raw):
        num = _first_number(raw)
        if num is not None and num > 0:
            return max(1, int(round(num)))
    if re.fullmatch(r"\d+", raw):
        return max(1, int(raw))
    return default


def _extract_piece_price_from_row(row: dict[str, Any]) -> float | None:
    for key in ("unit_price", "calc_note", "calc_method", "remark", "name", "spec"):
        price = _extract_piece_price_from_text(row.get(key))
        if price is not None and price > 0:
            return price
    return None


def _extract_piece_quantity_from_row(row: dict[str, Any]) -> int | None:
    for key in ("usage", "remark", "calc_note", "calc_method", "name"):
        qty = _extract_piece_quantity_from_text(row.get(key), default=None)
        if qty is not None:
            return qty
    return None


def _format_piece_usage(qty: int) -> str:
    return f"{max(1, int(qty))}个"


def _format_piece_unit_price(price: float) -> str:
    num = float(price)
    if abs(num - round(num)) < 1e-6:
        return f"{int(round(num))}元/个"
    return f"{num:g}元/个"


def try_normalize_badge_row_to_piece_pricing(row: dict[str, Any]) -> dict[str, Any] | None:
    """若行内已有明确个价/个数，改写为按个计价。"""
    piece_price = _extract_piece_price_from_row(row)
    if piece_price is None or piece_price <= 0:
        return None
    piece_qty = _extract_piece_quantity_from_row(row)
    if piece_qty is None:
        piece_qty = 1
    out = dict(row)
    out["usage"] = _format_piece_usage(piece_qty)
    out["unit_price"] = _format_piece_unit_price(piece_price)
    out["amount"] = round(piece_price * piece_qty, 2)
    out["usage_ai"] = False
    out["unit_price_ai"] = False
    out["amount_ai"] = False
    out.pop("badge_unit_conflict", None)
    out["badge_unit_normalized"] = True
    return out


def badge_accessory_unit_conflict_hints(row: dict[str, Any]) -> list[str]:
    if not isinstance(row, dict):
        return []
    name = str(row.get("name") or "").strip()
    if not is_count_badge_accessory(name, str(row.get("type") or ""), str(row.get("remark") or "")):
        return []
    if badge_accessory_uses_piece_units(row):
        return []
    if bool(row.get("badge_unit_conflict")):
        return [BADGE_UNIT_CONFLICT_REASON]
    if badge_accessory_uses_yard_units(row):
        return [BADGE_UNIT_CONFLICT_REASON]
    return []


def apply_badge_unit_guard_to_row(row: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(row, dict):
        return row
    name = str(row.get("name") or "").strip()
    mat_type = str(row.get("type") or row.get("material_type") or "").strip()
    remark = str(row.get("remark") or "").strip()
    if not is_count_badge_accessory(name, mat_type, remark):
        return row

    if badge_accessory_uses_piece_units(row):
        out = dict(row)
        out.pop("badge_unit_conflict", None)
        return out

    normalized = try_normalize_badge_row_to_piece_pricing(row)
    if normalized is not None:
        return normalized

    if not badge_accessory_uses_yard_units(row):
        out = dict(row)
        usage = str(out.get("usage") or "").strip()
        unit_price = str(out.get("unit_price") or "").strip()
        spec = str(out.get("spec") or "").strip()
        if (
            (not usage or usage in {"-", "—"})
            and (not unit_price or unit_price in {"-", "—"})
            and (not spec or _SPEC_ONLY_RE.match(spec))
        ):
            out["badge_unit_conflict"] = True
            out["recognition_status"] = "candidate_review"
            out["recognition_reason"] = BADGE_UNIT_CONFLICT_REASON
            out["exclude_from_cost"] = True
            out["amount_in_cost"] = False
            out.pop("amount", None)
        return out

    out = dict(row)
    out["badge_unit_conflict"] = True
    out["recognition_status"] = "candidate_review"
    out["recognition_reason"] = BADGE_UNIT_CONFLICT_REASON
    out["exclude_from_cost"] = True
    out["amount_in_cost"] = False
    out.pop("amount", None)
    out["usage_ai"] = False
    out["unit_price_ai"] = False
    out["amount_ai"] = False
    return out


def apply_badge_unit_guard(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [apply_badge_unit_guard_to_row(row) for row in items if isinstance(row, dict)]
