from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any
from urllib.parse import quote

from mcp_server.schemas import normalize_user_context
from quote_sheet_direct_prefill import build_direct_quote_sheet_prefill_payload
from quote_sheet_public_store import encode_public_quote_sheet_prefill_payload, save_public_quote_sheet_prefill


TOOL_NAME = "quote_archive"


def _failure(error: str) -> dict[str, Any]:
    return {"ok": False, "tool": TOOL_NAME, "error": error}


def _query_from_input(input_data: Any) -> dict[str, Any]:
    if not isinstance(input_data, dict):
        raise ValueError("input_data must be a dict.")
    query = input_data.get("query")
    if isinstance(query, dict):
        return dict(query)
    return dict(input_data)


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text and text.lower() not in {"null", "undefined", "nan"}:
            return text
    return ""


def _list_or_empty(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _first_summary(query: dict[str, Any]) -> dict[str, Any]:
    for key in (
        "summary",
        "quote_summary",
        "summaries",
        "\u62a5\u4ef7\u6c47\u603b",
        "\u62a5\u4ef7\u6863\u4f4d",
        "\u62a5\u4ef7\u8868",
    ):
        value = query.get(key)
        if isinstance(value, dict):
            return value
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    return item
    return {}


def _query_for_prefill(query: dict[str, Any]) -> dict[str, Any]:
    out = dict(query)
    if "summary" not in out:
        summary = _first_summary(out)
        if summary:
            out["summary"] = summary
    return out


def _quote_no(query: dict[str, Any], prefill: dict[str, Any]) -> str:
    meta = prefill.get("meta") if isinstance(prefill.get("meta"), dict) else {}
    quote_no = _first_text(
        meta.get("quote_no"),
        query.get("quote_no"),
        query.get("quote_sheet_no"),
        query.get("\u62a5\u4ef7\u5355\u53f7"),
    )
    if quote_no:
        return quote_no
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"GPT-{stamp}"


def _sales_identity(input_data: dict[str, Any], query: dict[str, Any], prefill: dict[str, Any]) -> tuple[str, str]:
    user_context = normalize_user_context(input_data.get("user_context"))
    meta = prefill.get("meta") if isinstance(prefill.get("meta"), dict) else {}
    sales_user_id = _first_text(
        user_context.get("sales_user_id"),
        user_context.get("user_id"),
        query.get("sales_user_id"),
        query.get("salesperson"),
        "gpt_action",
    )
    sales_user_name = _first_text(
        user_context.get("sales_user_name"),
        user_context.get("user_name"),
        meta.get("seller_contact"),
        query.get("sales_user_name"),
        query.get("salesperson"),
        "GPT",
    )
    return sales_user_id, sales_user_name


def _summaries(query: dict[str, Any], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    raw = query.get("summaries")
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    summary = _first_summary(query)
    if isinstance(summary, dict) and summary:
        return [summary]
    summaries: list[dict[str, Any]] = []
    for row in rows:
        summaries.append(
            {
                "quantity": row.get("qty"),
                "exw": row.get("price"),
                "amount": row.get("total"),
                "remark": row.get("note"),
            }
        )
    return summaries


def _archive_payload(
    input_data: dict[str, Any],
    query: dict[str, Any],
) -> tuple[dict[str, Any], str, str, dict[str, Any]]:
    prefill = build_direct_quote_sheet_prefill_payload(_query_for_prefill(query))
    rows = [row for row in _list_or_empty(prefill.get("rows")) if isinstance(row, dict)]
    if not rows:
        raise ValueError("missing product rows for backend archive.")

    meta = prefill.get("meta") if isinstance(prefill.get("meta"), dict) else {}
    quote_no = _quote_no(query, prefill)
    sales_user_id, sales_user_name = _sales_identity(input_data, query, prefill)
    payload = {
        "quote_no": quote_no,
        "quote_sheet_no": quote_no,
        "salesperson": _first_text(meta.get("seller_contact"), query.get("salesperson"), sales_user_name),
        "customer_name": _first_text(meta.get("cust_name"), query.get("customer_name"), query.get("cust_name")),
        "customer_country": _first_text(meta.get("cust_addr"), query.get("customer_country")),
        "currency_unit": _first_text(query.get("currency_unit"), "RMB/pc"),
        "products": rows,
        "quote_sheet_rows": rows,
        "materials": _list_or_empty(query.get("materials")),
        "summaries": _summaries(query, rows),
        "risks": _list_or_empty(query.get("risks")),
        "usage_calculation": _list_or_empty(query.get("usage_calculation")),
        "source_file_name": _first_text(query.get("source_file_name"), query.get("file_name"), "GPT backend archive"),
    }
    company = query.get("company")
    if isinstance(company, dict):
        payload["company"] = company
    payment = query.get("payment")
    if isinstance(payment, dict):
        payload["payment"] = payment
    return payload, sales_user_id, sales_user_name, prefill


def _public_base_url() -> str:
    for key in ("PUBLIC_MCP_BASE_URL", "AUTOQUOTE_PUBLIC_BASE_URL", "RENDER_EXTERNAL_URL"):
        value = str(os.environ.get(key) or "").strip().rstrip("/")
        if value:
            return value
    hostname = str(os.environ.get("RENDER_EXTERNAL_HOSTNAME") or "").strip().strip("/")
    if hostname:
        return f"https://{hostname}"
    service_name = str(os.environ.get("RENDER_SERVICE_NAME") or "").strip()
    if service_name:
        return f"https://{service_name}.onrender.com"
    return ""


def _absolute_or_relative_url(path: str) -> str:
    base = _public_base_url()
    return f"{base}{path}" if base else path


def _quote_sheet_prefill_urls(prefill: dict[str, Any], query: dict[str, Any]) -> dict[str, str]:
    token = save_public_quote_sheet_prefill(prefill)
    payload_fallback = encode_public_quote_sheet_prefill_payload(prefill)
    preview_path = f"/?view=quoteSheet&quote_sheet_token={quote(token)}"
    if payload_fallback:
        preview_path = f"{preview_path}&quote_sheet_payload={quote(payload_fallback)}"
    export_mode = str(query.get("export_mode") or query.get("exportMode") or "").strip().lower()
    download_mode = "pdf_fob" if export_mode == "pdf_fob" else "pdf_rmb"
    download_path = f"{preview_path}&exportMode={download_mode}"
    return {
        "quote_sheet_preview_url": _absolute_or_relative_url(preview_path),
        "quote_sheet_download_url": _absolute_or_relative_url(download_path),
    }


def quote_archive(input_data: dict[str, Any] | None = None) -> dict[str, Any]:
    data = input_data if isinstance(input_data, dict) else {}
    try:
        query = _query_from_input(data)
        payload, sales_user_id, sales_user_name, prefill = _archive_payload(data, query)

        from quote_import_store import import_quote_payload

        saved = import_quote_payload(
            payload,
            sales_user_id=sales_user_id,
            sales_user_name=sales_user_name,
        )
        backend_received = bool(saved.get("success"))
        quote_sheet_urls = _quote_sheet_prefill_urls(prefill, query) if backend_received else {}
        return {
            "ok": backend_received,
            "tool": TOOL_NAME,
            "result": {
                "backend_received": backend_received,
                "quote_uid": str(saved.get("quote_uid") or ""),
                "calc_quote_id": str(saved.get("quote_id") or ""),
                "version_id": saved.get("version_id"),
                "version_no": saved.get("version_no"),
                "preview_url": quote_sheet_urls.get("quote_sheet_preview_url", ""),
                "download_url": quote_sheet_urls.get("quote_sheet_download_url", ""),
                **quote_sheet_urls,
                "status": "imported" if backend_received else "failed",
            },
        }
    except Exception as exc:  # noqa: BLE001
        return _failure(str(exc))
