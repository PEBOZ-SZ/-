from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


MAX_PRODUCT_ROWS = 10
INTERNAL_NOTE_KEYWORDS = (
    "刀模",
    "模具",
    "摊销",
    "AI暂估",
    "待确认",
    "毛利",
    "管理费",
    "加工费",
    "成本",
    "物料",
    "EXW",
    "FOB",
)


def _first_str(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text and text != "-":
            return text
    return ""


def _format_text_number(value: Any) -> str:
    raw = _first_str(value)
    if not raw:
        return ""
    try:
        from display_number_format import format_numbers_in_display_text

        return format_numbers_in_display_text(raw)
    except Exception:
        return raw


def _pick(obj: dict[str, Any], *keys: str) -> str:
    if not isinstance(obj, dict):
        return ""
    for key in keys:
        if key in obj:
            text = _first_str(obj.get(key))
            if text:
                return text
    return ""


def _format_size_value(value: Any) -> str:
    if isinstance(value, dict):
        length = _pick(value, "length_cm", "l_cm", "LCM", "length", "L")
        width = _pick(value, "width_cm", "w_cm", "WCM", "width", "W")
        height = _pick(value, "height_cm", "h_cm", "HCM", "height", "H")
        parts = [part for part in (length, width, height) if part]
        if len(parts) >= 2:
            return "×".join(parts) + "cm"
    return _first_str(value)


def _pick_size(*objects: dict[str, Any]) -> str:
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        for key in ("size", "product_size", "dimensions", "dimension", "spec", "specification"):
            if key in obj:
                text = _format_size_value(obj.get(key))
                if text:
                    return text
    return ""


def _first_tier(raw: dict[str, Any]) -> dict[str, Any]:
    tiers = raw.get("tiers")
    if isinstance(tiers, list):
        for tier in tiers:
            if isinstance(tier, dict):
                return tier
    return {}


def _parse_float(value: Any) -> float | None:
    text = _first_str(value).replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _format_amount_from_qty_price(qty: str, price: str) -> str:
    qty_num = _parse_float(qty)
    price_num = _parse_float(price)
    if qty_num is None or price_num is None:
        return ""
    return _format_text_number(qty_num * price_num)


def _customer_note(*objects: dict[str, Any]) -> str:
    for obj in objects:
        note = _pick(obj, "customer_note", "customer_remark", "quote_sheet_note", "visible_note")
        if not note:
            continue
        upper = note.upper()
        if any(keyword.upper() in upper for keyword in INTERNAL_NOTE_KEYWORDS):
            return ""
        return note
    return ""


def _source(raw: dict[str, Any]) -> dict[str, Any]:
    data = raw.get("prefill") if isinstance(raw.get("prefill"), dict) else raw
    for key in ("quote_sheet", "quote_result", "result", "calculated_quote", "quotation"):
        nested = data.get(key)
        if isinstance(nested, dict):
            return nested
    return data


def _direct_meta(raw: dict[str, Any]) -> dict[str, str]:
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    quote_meta = raw.get("quote_sheet_meta") if isinstance(raw.get("quote_sheet_meta"), dict) else {}
    src = {**quote_meta, **meta}
    quote_date = _pick(src, "quote_date_iso", "quote_date", "date")
    out = {
        "quote_no": _pick(src, "quote_no", "quote_sheet_no"),
        "seller_contact": _pick(src, "seller_contact", "seller", "sales_name", "salesperson"),
        "seller_email": _pick(src, "seller_email", "sales_email", "email"),
        "cust_name": _pick(src, "cust_name", "customer_name", "customer", "client_name"),
        "cust_contact": _pick(src, "cust_contact", "customer_contact", "contact"),
        "cust_phone": _pick(src, "cust_phone", "customer_phone", "phone"),
        "cust_addr": _pick(src, "cust_addr", "customer_address", "address"),
        "quote_date_iso": quote_date[:10] if quote_date else datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "sample_required": _pick(src, "sample_required"),
        "sample_fee": _pick(src, "sample_fee"),
        "sample_lead_time": _pick(src, "sample_lead_time"),
        "payee_account_type": _pick(src, "payee_account_type"),
        "payee_account_id": _pick(src, "payee_account_id"),
        "payee_company_name": _pick(src, "payee_company_name"),
    }
    for key in ("co_name", "co_phone", "co_addr"):
        value = _pick(src, key)
        if value:
            out[key] = value
    return out


def _candidate_rows_with_source(raw: dict[str, Any]) -> tuple[str, list[Any]]:
    for key in ("quote_sheet_rows", "product_rows", "products", "rows", "items"):
        value = raw.get(key)
        if isinstance(value, list):
            return key, value
    return "", []


def _candidate_rows(raw: dict[str, Any]) -> list[Any]:
    return _candidate_rows_with_source(raw)[1]


def _direct_rows(raw: dict[str, Any]) -> list[dict[str, Any]]:
    source_key, candidates = _candidate_rows_with_source(raw)
    source_rows = [item for item in candidates if isinstance(item, dict)]
    item = source_rows[0] if source_rows else {}
    tier = _first_tier(raw)
    item_first = source_key != "items"
    qty_sources = (item, tier, raw) if item_first else (raw, tier, item)
    price_sources = (item, tier, raw) if item_first else (raw, tier, item)
    total_sources = (item, tier, raw) if item_first else (raw, tier, item)
    qty = ""
    for src in qty_sources:
        qty = _pick(src, "qty", "quantity", "count")
        if qty:
            break
    price = ""
    for src in price_sources:
        price = _format_text_number(_pick(src, "price", "unit_price", "unitPrice", "exw_price", "fob_price", "exw"))
        if price:
            break
    total = ""
    for src in total_sources:
        total = _format_text_number(_pick(src, "total", "amount", "subtotal", "line_total"))
        if total:
            break
    if not total:
        total = _format_amount_from_qty_price(qty, price)
    row = {
        "line_order": 0,
        "name": _pick(raw, "product_name", "quote_product_name", "product", "name")
        or _pick(item, "product_name", "quote_product_name", "item_name", "name"),
        "size": _pick_size(raw, item),
        "desc": _pick(raw, "customer_description", "quote_sheet_description", "description", "desc")
        or _pick(item, "customer_description", "quote_sheet_description", "description", "desc", "scope"),
        "pack": _pick(raw, "pack", "packing", "packaging", "package")
        or _pick(item, "pack", "packing", "packaging", "package"),
        "qty": qty,
        "price": price,
        "total": total,
        "note": _customer_note(raw, item),
        "taxed_price": _format_text_number(_pick(item, "taxed_price", "taxed_price_text")),
        "fob_price": _format_text_number(_pick(item, "fob_price", "fob_unit_price")),
        "fob_price_text": _format_text_number(_pick(item, "fob_price_text")),
        "fob_price_usd": _format_text_number(_pick(item, "fob_price_usd", "unit_price_usd")),
        "fob_price_usd_text": _format_text_number(_pick(item, "fob_price_usd_text")),
        "fob_total": _format_text_number(_pick(item, "fob_total")),
        "fob_total_usd": _format_text_number(_pick(item, "fob_total_usd")),
        "image_data_url": _pick(raw, "image_data_url", "image_url", "image", "product_image")
        or _pick(item, "image_data_url", "image_url", "image", "product_image"),
    }
    if any(_first_str(row.get(key)) for key in ("name", "size", "desc", "pack", "qty", "price", "total")):
        return [row]
    return []


def build_direct_quote_sheet_prefill_payload(raw: dict[str, Any]) -> dict[str, Any]:
    data = _source(raw if isinstance(raw, dict) else {})
    rows = _direct_rows(data)
    product_name = _first_str(
        data.get("product_name"),
        data.get("name"),
        rows[0].get("name") if rows else "",
    )
    price_type = _first_str(data.get("price_type"), data.get("trade_term"), data.get("incoterm"))
    fob_quote = bool(data.get("fob_quote") or data.get("include_fob") or "FOB" in price_type.upper())
    return {
        "ok": True,
        "source": "gpt_direct",
        "quote_series_uid": "",
        "meta": _direct_meta(data),
        "rows": rows,
        "usd_cny_rate": data.get("usd_cny_rate") or data.get("exchange_rate"),
        "fob_yuan_per_pc": data.get("fob_yuan_per_pc") or data.get("fob_addition_per_piece"),
        "product_name": product_name,
        "fob_quote": fob_quote,
        "suggested_export_lang": "en" if fob_quote else "cn",
        "include_fob": data.get("include_fob"),
        "price_type": price_type,
    }
