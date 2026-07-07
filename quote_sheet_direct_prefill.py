from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


MAX_PRODUCT_ROWS = 10


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


def _source(raw: dict[str, Any]) -> dict[str, Any]:
    data = raw.get("prefill") if isinstance(raw.get("prefill"), dict) else raw
    return data.get("quote_sheet") if isinstance(data.get("quote_sheet"), dict) else data


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


def _candidate_rows(raw: dict[str, Any]) -> list[Any]:
    for key in ("rows", "quote_sheet_rows", "products", "items"):
        value = raw.get(key)
        if isinstance(value, list):
            return value
    return []


def _direct_rows(raw: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ix, item in enumerate(_candidate_rows(raw)[:MAX_PRODUCT_ROWS]):
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "line_order": ix,
                "name": _pick(item, "name", "product_name", "item_name", "material_name"),
                "size": _pick(item, "size", "spec", "specification", "dimensions"),
                "desc": _pick(item, "desc", "description", "scope"),
                "pack": _pick(item, "pack", "packing", "packaging"),
                "qty": _pick(item, "qty", "quantity", "count", "usage"),
                "price": _format_text_number(_pick(item, "price", "unit_price", "unitPrice")),
                "total": _format_text_number(_pick(item, "total", "amount", "subtotal", "line_total")),
                "note": _pick(item, "note", "remark", "remarks"),
                "taxed_price": _format_text_number(_pick(item, "taxed_price", "taxed_price_text")),
                "fob_price": _format_text_number(_pick(item, "fob_price", "fob_unit_price")),
                "fob_price_text": _format_text_number(_pick(item, "fob_price_text")),
                "fob_price_usd": _format_text_number(_pick(item, "fob_price_usd", "unit_price_usd")),
                "fob_price_usd_text": _format_text_number(_pick(item, "fob_price_usd_text")),
                "fob_total": _format_text_number(_pick(item, "fob_total")),
                "fob_total_usd": _format_text_number(_pick(item, "fob_total_usd")),
                "image_data_url": _pick(item, "image_data_url", "image_url", "image"),
            }
        )
    return rows


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
