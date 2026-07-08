"""Import GPT-produced quote sheet rows into the existing quote persistence."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import quote_upload_storage


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text and text.lower() not in {"null", "undefined", "nan"}:
            return text
    return ""


def _number_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _display_number(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, str):
        return value.strip()
    num = _number_or_none(value)
    if num is None:
        return str(value).strip()
    return f"{num:.4f}".rstrip("0").rstrip(".")


def _size_from_product(product: dict[str, Any]) -> str:
    size = _first_text(product.get("size"), product.get("size_cm"), product.get("尺寸"))
    if size and not isinstance(product.get("size_cm"), dict):
        return size
    dims = product.get("size_cm")
    if not isinstance(dims, dict):
        return size
    parts = [
        _display_number(dims.get("length")),
        _display_number(dims.get("width")),
        _display_number(dims.get("height")),
    ]
    parts = [p for p in parts if p]
    return "×".join(parts) + ("cm" if parts else "")


def _normalize_quote_sheet_row(
    row: dict[str, Any],
    *,
    product: dict[str, Any] | None = None,
    summary: dict[str, Any] | None = None,
) -> dict[str, str]:
    product = product if isinstance(product, dict) else {}
    summary = summary if isinstance(summary, dict) else {}
    qty = _first_text(
        row.get("qty"),
        row.get("quantity"),
        row.get("数量"),
        summary.get("quantity"),
    )
    price = _first_text(
        row.get("price"),
        row.get("unit_price"),
        row.get("单价"),
        row.get("fob"),
        row.get("exw"),
        summary.get("fob"),
        summary.get("exw"),
    )
    total = _first_text(row.get("total"), row.get("amount"), row.get("总价"))
    qty_num = _number_or_none(qty)
    price_num = _number_or_none(price)
    if not total and qty_num is not None and price_num is not None:
        total = _display_number(qty_num * price_num)
    return {
        "name": _first_text(
            row.get("name"),
            row.get("product_name"),
            row.get("名称"),
            product.get("name"),
            product.get("type"),
        ),
        "size": _first_text(row.get("size"), row.get("尺寸"), _size_from_product(product)),
        "desc": _first_text(
            row.get("desc"),
            row.get("description"),
            row.get("描述"),
            product.get("description"),
        ),
        "pack": _first_text(row.get("pack"), row.get("package"), row.get("packaging"), row.get("包装")),
        "qty": _display_number(qty),
        "price": _display_number(price),
        "total": _display_number(total),
        "note": _first_text(row.get("note"), row.get("remark"), row.get("备注")),
        "image_data_url": _first_text(row.get("image_data_url"), row.get("image"), row.get("图片")),
    }


def _normalize_product_rows(payload: dict[str, Any]) -> list[dict[str, str]]:
    product = payload.get("product") if isinstance(payload.get("product"), dict) else {}
    summaries = payload.get("summaries") if isinstance(payload.get("summaries"), list) else []
    products = payload.get("products")
    if not isinstance(products, list):
        products = payload.get("quote_sheet_rows")
    rows: list[dict[str, str]] = []
    if isinstance(products, list):
        for index, raw in enumerate(products):
            if not isinstance(raw, dict):
                continue
            summary = summaries[index] if index < len(summaries) and isinstance(summaries[index], dict) else None
            row = _normalize_quote_sheet_row(raw, product=product, summary=summary)
            if any(row.get(key) for key in ("name", "size", "desc", "qty", "price", "total")):
                rows.append(row)
    if not rows and product:
        summary = summaries[0] if summaries and isinstance(summaries[0], dict) else None
        row = _normalize_quote_sheet_row({}, product=product, summary=summary)
        if any(row.get(key) for key in ("name", "size", "desc", "qty", "price", "total")):
            rows.append(row)
    return rows


def _normalize_material_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    materials = payload.get("materials")
    if not isinstance(materials, list):
        return []
    rows: list[dict[str, Any]] = []
    for raw in materials:
        if not isinstance(raw, dict):
            continue
        amount = raw.get("amount")
        amount_num = _number_or_none(amount)
        rows.append(
            {
                "name": _first_text(raw.get("name"), raw.get("material"), raw.get("材料")),
                "spec": _first_text(raw.get("spec"), raw.get("规格")),
                "usage": _first_text(raw.get("usage"), raw.get("用量")),
                "unit_price": _first_text(raw.get("unit_price"), raw.get("price"), raw.get("单价")),
                "amount": amount_num if amount_num is not None else 0,
                "amount_text": _display_number(amount),
                "source": "gpt_quote_import",
                "calc_note": _first_text(raw.get("remark"), raw.get("note"), raw.get("备注")),
                "kb_hit": "知识库" in _first_text(raw.get("remark"), raw.get("note"), raw.get("备注")),
            }
        )
    return rows


def _meta_from_payload(payload: dict[str, Any], quote_no: str, sales_user_name: str) -> dict[str, str]:
    company = payload.get("company") if isinstance(payload.get("company"), dict) else {}
    payment = payload.get("payment") if isinstance(payload.get("payment"), dict) else {}
    meta = {
        "quote_no": quote_no,
        "quote_no_manual": True,
        "seller_contact": _first_text(payload.get("salesperson"), sales_user_name),
        "cust_name": _first_text(payload.get("customer_name"), payload.get("cust_name")),
        "cust_addr": _first_text(payload.get("customer_country"), payload.get("customer_address")),
        "quote_date_iso": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }
    if company:
        meta.update(
            {
                "co_name": _first_text(company.get("name")),
                "co_phone": _first_text(company.get("phone")),
                "co_addr": _first_text(company.get("address")),
            }
        )
    if payment:
        meta.update(
            {
                "payee_company_name": _first_text(payment.get("receiver")),
                "payee_account_id": _first_text(payment.get("account"), payment.get("alipay")),
            }
        )
    return {key: value for key, value in meta.items() if value}


def _tiers_from_summaries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    summaries = payload.get("summaries")
    if not isinstance(summaries, list):
        return []
    tiers: list[dict[str, Any]] = []
    for raw in summaries:
        if not isinstance(raw, dict):
            continue
        tiers.append(
            {
                "quantity": raw.get("quantity"),
                "material_total": raw.get("material_total"),
                "processing_fee": raw.get("labor_fee"),
                "management_fee": raw.get("management_fee"),
                "cost_before_margin": raw.get("production_cost"),
                "exw_price": raw.get("exw"),
                "fob_price": raw.get("fob"),
                "gross_margin_rate": raw.get("margin"),
                "profit": raw.get("profit"),
                "remark": raw.get("remark"),
            }
        )
    return tiers


def import_quote_payload(
    payload: dict[str, Any],
    *,
    sales_user_id: str | None = None,
    sales_user_name: str | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("请求体必须是 JSON 对象。")
    quote_no = _first_text(payload.get("quote_no"), payload.get("quote_sheet_no"))
    if not quote_no:
        raise ValueError("缺少 quote_no。")
    rows = _normalize_product_rows(payload)
    if not rows:
        raise ValueError("缺少产品行，请提供 products 或 product。")

    sid = _first_text(sales_user_id, payload.get("sales_user_id"), payload.get("salesperson"), "gpt_action")
    sname = _first_text(sales_user_name, payload.get("sales_user_name"), payload.get("salesperson"), sid)
    quote_uid = quote_no
    calc_quote_id = f"gpt-import-{quote_no}-{uuid.uuid4().hex[:10]}"
    source_file_name = _first_text(payload.get("source_file_name"), payload.get("file_name"))
    detail_rows = _normalize_material_rows(payload)
    tiers = _tiers_from_summaries(payload)
    material_total = None
    if tiers:
        material_total = tiers[0].get("material_total")
    quote_result: dict[str, Any] = {
        "quote_id": calc_quote_id,
        "quote_series_uid": quote_uid,
        "quote_no": quote_no,
        "quote_sheet_no": quote_no,
        "quote_mode": "gpt_quote_import",
        "validation_status": "imported",
        "product_name": rows[0].get("name", ""),
        "customer_name": _first_text(payload.get("customer_name"), payload.get("cust_name")),
        "customer_country": _first_text(payload.get("customer_country")),
        "currency_unit": _first_text(payload.get("currency_unit")),
        "source_file_name": source_file_name,
        "quote_sheet_meta": _meta_from_payload(payload, quote_no, sname),
        "quote_sheet_rows": rows,
        "detail_rows": detail_rows,
        "tiers": tiers,
        "material_total": material_total,
        "risks": payload.get("risks") if isinstance(payload.get("risks"), list) else [],
        "usage_calculation": payload.get("usage_calculation")
        if isinstance(payload.get("usage_calculation"), list)
        else [],
        "source_summary": {
            "source": "gpt_quote_import",
            "source_file_name": source_file_name,
            "quote_no": quote_no,
        },
        "structured_input": payload,
    }
    quote_upload_storage.finalize_quote_persistence(
        quote_series_uid=quote_uid,
        quote_result=quote_result,
        uploaded_sheet=None,
        sheet_original_display_name=source_file_name,
        sales_user_id=sid,
        sales_user_name=sname,
        structured_input=payload,
        quote_mode="gpt_quote_import",
        validation_status="imported",
        source_summary=quote_result["source_summary"],
    )
    saved = quote_upload_storage.resolve_quote_version_target(quote_uid, calc_quote_id=calc_quote_id) or {}
    preview_url = "/?" + urlencode({"view": "quoteSheet", "quote_uid": quote_uid})
    return {
        "success": True,
        "quote_id": calc_quote_id,
        "quote_no": quote_no,
        "quote_uid": quote_uid,
        "version_id": saved.get("id"),
        "version_no": saved.get("version_no"),
        "preview_url": preview_url,
    }
