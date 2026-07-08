from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


MAX_PRODUCT_ROWS = 10
NAME_KEYS = ("product_name", "quote_product_name", "product", "name", "产品名称", "产品名", "品名", "名称")
SIZE_KEYS = ("size", "product_size", "dimensions", "dimension", "spec", "specification", "尺寸", "规格尺寸", "规格")
DESC_KEYS = (
    "customer_description",
    "quote_sheet_description",
    "description",
    "desc",
    "scope",
    "描述",
    "产品描述",
    "说明",
)
PACK_KEYS = ("pack", "packing", "packaging", "package", "包装", "包装方式", "包装信息")
QTY_KEYS = ("qty", "quantity", "count", "数量", "报价数量", "订单数量", "个数", "PCS")
PRICE_KEYS = (
    "price",
    "unit_price",
    "unitPrice",
    "exw_price",
    "fob_price",
    "exw",
    "EXW",
    "EXW单价",
    "EXW价",
    "FOB单价",
    "FOB价",
    "单价",
    "报价单价",
    "客户单价",
    "出厂价",
)
TOTAL_KEYS = ("total", "amount", "subtotal", "line_total", "总价", "金额", "小计", "合计", "总金额", "报价金额")
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
PRODUCT_IMAGE_VALUE_KEYS = (
    "product_image_data_url",
    "product_image_url",
    "product_photo",
    "product_photo_url",
    "style_image_data_url",
    "style_image_url",
    "main_image_data_url",
    "main_image_url",
    "款式图片",
    "产品图片",
    "包图",
    "product_image",
)
GENERIC_IMAGE_VALUE_KEYS = ("image_data_url", "image_url", "data_url", "image")
IMAGE_CONTEXT_KEYS = (
    "image_role",
    "image_type",
    "image_source",
    "source_role",
    "caption",
    "label",
    "file_name",
    "filename",
    "original_name",
    "source_path",
    "tags",
)
REJECT_IMAGE_KEYWORDS = (
    "bom",
    "material",
    "materials",
    "cutting",
    "piece",
    "structure",
    "spec",
    "table",
    "sheet",
    "excel",
    "worksheet",
    "spreadsheet",
    "receipt",
    "invoice",
    "logo",
    "barcode",
    "qr",
    "物料",
    "材料",
    "裁片",
    "结构",
    "表格",
    "截图",
    "明细",
    "工艺",
    "包装表",
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


def _image_context(obj: dict[str, Any], key: str = "") -> str:
    if not isinstance(obj, dict):
        return str(key or "").strip().lower()
    parts: list[str] = [str(key or "")]
    for ctx_key in IMAGE_CONTEXT_KEYS:
        value = obj.get(ctx_key)
        if value is None:
            continue
        if isinstance(value, (list, tuple, set)):
            parts.extend(str(item) for item in value if item)
        else:
            parts.append(str(value))
    return " ".join(parts).strip().lower()


def _looks_like_image_value(value: Any) -> bool:
    text = _first_str(value)
    if not text:
        return False
    if text.lower() in {"true", "false", "yes", "no", "1", "0"}:
        return False
    return True


def _is_rejected_image_candidate(obj: dict[str, Any], key: str) -> bool:
    context = _image_context(obj, key)
    if any(keyword in context for keyword in REJECT_IMAGE_KEYWORDS):
        return True
    try:
        from quote_sheet_content import has_non_product_image_keywords

        return bool(has_non_product_image_keywords(context))
    except Exception:
        return False


def _pick_image_value_from_obj(obj: dict[str, Any], keys: tuple[str, ...]) -> str:
    if not isinstance(obj, dict):
        return ""
    for key in keys:
        if key not in obj or not _looks_like_image_value(obj.get(key)):
            continue
        if _is_rejected_image_candidate(obj, key):
            continue
        return _first_str(obj.get(key))
    return ""


def _pick_image_from_list(values: Any) -> str:
    if not isinstance(values, list):
        return ""
    candidates = [item for item in values if isinstance(item, dict)]
    product_first = sorted(
        candidates,
        key=lambda item: 0
        if str(item.get("product_image") or item.get("image_type") or item.get("image_role") or "")
        .strip()
        .lower()
        in {"1", "true", "product", "product_photo", "style", "main", "款式图", "产品图"}
        else 1,
    )
    for item in product_first:
        image = _pick_image_value_from_obj(item, PRODUCT_IMAGE_VALUE_KEYS + GENERIC_IMAGE_VALUE_KEYS)
        if image:
            return image
    return ""


def _pick_product_image(*objects: dict[str, Any]) -> str:
    for obj in objects:
        image = _pick_image_value_from_obj(obj, PRODUCT_IMAGE_VALUE_KEYS)
        if image:
            return image
    for obj in objects:
        image = _pick_image_value_from_obj(obj, GENERIC_IMAGE_VALUE_KEYS)
        if image:
            return image
    for obj in objects:
        if not isinstance(obj, dict):
            continue
        for key in ("product_images", "quote_sheet_images", "images", "attachments", "files"):
            image = _pick_image_from_list(obj.get(key))
            if image:
                return image
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
        for key in SIZE_KEYS:
            if key in obj:
                text = _format_size_value(obj.get(key))
                if text:
                    return text
    return ""


def _first_tier(raw: dict[str, Any]) -> dict[str, Any]:
    for key in ("tiers", "quote_tiers", "price_tiers", "quotes", "summaries", "报价汇总", "报价档位", "报价表"):
        tiers = raw.get(key)
        if isinstance(tiers, list):
            for tier in tiers:
                if isinstance(tier, dict):
                    return tier
        if isinstance(tiers, dict):
            return tiers
    summary = raw.get("summary") or raw.get("quote_summary") or raw.get("汇总")
    if isinstance(summary, dict):
        return summary
    if isinstance(summary, list):
        for tier in summary:
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
        note = _pick(obj, "customer_note", "customer_remark", "quote_sheet_note", "visible_note", "客户备注")
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
    for key in ("quote_sheet_rows", "product_rows", "products", "rows", "产品明细", "产品行", "报价汇总", "items"):
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
    item_first = source_key not in {"items", "报价汇总"}
    qty_sources = (item, tier, raw) if item_first else (raw, tier, item)
    price_sources = (item, tier, raw) if item_first else (raw, tier, item)
    total_sources = (item, tier, raw) if item_first else (raw, tier, item)
    qty = ""
    for src in qty_sources:
        qty = _pick(src, *QTY_KEYS)
        if qty:
            break
    price = ""
    for src in price_sources:
        price = _format_text_number(_pick(src, *PRICE_KEYS))
        if price:
            break
    total = ""
    for src in total_sources:
        total = _format_text_number(_pick(src, *TOTAL_KEYS))
        if total:
            break
    if not total:
        total = _format_amount_from_qty_price(qty, price)
    row = {
        "line_order": 0,
        "name": _pick(raw, *NAME_KEYS) or _pick(item, *NAME_KEYS, "item_name"),
        "size": _pick_size(raw, item),
        "desc": _pick(raw, *DESC_KEYS) or _pick(item, *DESC_KEYS),
        "pack": _pick(raw, *PACK_KEYS) or _pick(item, *PACK_KEYS),
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
        "image_data_url": _pick_product_image(raw, item),
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
