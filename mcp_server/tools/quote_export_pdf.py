from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import quote_upload_storage
from mcp_server.audit import write_audit_log
from mcp_server.auth import ROLE_ADMIN, ROLE_SALES, ROLE_SYSTEM_ADMIN, require_tool_permission
from mcp_server.sanitizer import sanitize_quote_export_pdf_result
from mcp_server.schemas import normalize_user_context, validate_quote_export_pdf_input
from quote_sheet_export_validate import validate_quote_sheet_export_payload
from quote_sheet_i18n import translate_quote_sheet_fields
from quote_sheet_prefill import build_quote_sheet_prefill_payload_for_mcp


TOOL_NAME = "quote_export_pdf"
QUOTE_EXPORT_PDF_DIR = Path("exports") / "quote_pdfs"
SAFE_NOT_FOUND = "报价不存在或无权访问。"


def _failure(error: str) -> dict[str, Any]:
    return {"ok": False, "tool": TOOL_NAME, "error": error}


def _safe_text(value: Any, default: str = "-") -> str:
    text = str(value if value is not None else "").strip()
    return text or default


def _safe_slug(value: Any) -> str:
    text = str(value or "").strip() or "quote"
    text = re.sub(r"[^0-9A-Za-z_.-]+", "_", text)
    return text.strip("._") or "quote"


def _resolve_detail(query: dict[str, Any]) -> dict[str, Any] | None:
    return quote_upload_storage.load_quote_detail_for_mcp(
        quote_uid=query["quote_uid"],
        calc_quote_id=query["calc_quote_id"],
        version_id=query["version_id"],
        version_no=query["version_no"],
        include_quote_json=True,
        include_files=False,
        include_chat_messages=False,
    )


def _needs_user_completion(meta: dict[str, Any]) -> list[str]:
    needs: list[str] = []
    checks = [
        ("payee_account", ("payee_account_type", "payee_account_id", "payee_company_name")),
        ("sample_required", ("sample_required",)),
        ("sample_fee", ("sample_fee",)),
        ("sample_lead_time", ("sample_lead_time",)),
    ]
    for label, keys in checks:
        value_present = any(str(meta.get(key) or "").strip() for key in keys)
        if label == "sample_required":
            value_present = str(meta.get("sample_required") or "").strip().lower() in {"yes", "no"}
        if not value_present:
            needs.append(label)
    return needs


def _prefill_summary(prefill: dict[str, Any], detail: dict[str, Any]) -> dict[str, Any]:
    meta = prefill.get("meta") if isinstance(prefill.get("meta"), dict) else {}
    rows = prefill.get("rows") if isinstance(prefill.get("rows"), list) else []
    product_name = _safe_text(detail.get("product_name") or prefill.get("product_name"), "")
    return {
        "quote_no": str(meta.get("quote_no") or ""),
        "customer_name": str(meta.get("cust_name") or ""),
        "product_name": product_name,
        "rows_count": len(rows),
        "has_images": any(
            isinstance(row, dict) and bool(str(row.get("image_data_url") or "").strip())
            for row in rows
        ),
        "suggested_export_lang": str(prefill.get("suggested_export_lang") or "cn"),
        "fob_quote": bool(prefill.get("fob_quote")),
        "needs_user_completion": _needs_user_completion(meta),
    }


def _payee_from_meta(meta: dict[str, Any]) -> dict[str, Any]:
    company = _safe_text(meta.get("payee_company_name"), "")
    account_type = _safe_text(meta.get("payee_account_type"), "")
    account_id = _safe_text(meta.get("payee_account_id"), "")
    return {
        "company_name": company or "PEBOZ",
        "account_type": account_type,
        "bank_account": account_id,
    }


def _export_bundle(prefill: dict[str, Any], lang: str) -> dict[str, Any]:
    meta = prefill.get("meta") if isinstance(prefill.get("meta"), dict) else {}
    rows = prefill.get("rows") if isinstance(prefill.get("rows"), list) else []
    bundle = {
        "meta": meta,
        "rows": rows,
        "payee": _payee_from_meta(meta),
        "selected_bank_account_type": _safe_text(meta.get("payee_account_type"), ""),
    }
    if lang in {"en", "bilingual"}:
        bundle.update(translate_quote_sheet_fields(bundle))
    return bundle


def _validation_missing_fields(validation: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    issues = validation.get("blocking_issues")
    if isinstance(issues, list):
        for issue in issues:
            if isinstance(issue, dict):
                key = str(issue.get("key") or "").strip()
                if key:
                    missing.append(key)
    return missing


def _approval_status(detail: dict[str, Any]) -> str:
    return str(detail.get("approval_status") or "pending").strip().lower() or "pending"


def _approval_note(detail: dict[str, Any]) -> str:
    return str(detail.get("approval_note") or "").strip()


def _approval_block_message(detail: dict[str, Any]) -> str:
    status = _approval_status(detail)
    note = _approval_note(detail)
    if status == "rejected":
        suffix = f" 驳回原因：{note}" if note else ""
        return f"报价已被驳回，请查看驳回原因并修改后重新提交。{suffix}"
    if status == "pending":
        return "报价待管理员审批，审批通过后才能导出正式报价单。"
    return f"报价审批状态为 {status}，审批通过后才能导出正式报价单。"


def _display_rows(bundle: dict[str, Any], lang: str, currency_mode: str) -> list[dict[str, Any]]:
    if lang == "en":
        rows = bundle.get("rows_en") if isinstance(bundle.get("rows_en"), list) else bundle.get("rows")
    else:
        rows = bundle.get("rows") if isinstance(bundle.get("rows"), list) else []
    out = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        price = row.get("price")
        total = row.get("total")
        if currency_mode == "fob_usd":
            price = row.get("fob_price_usd") or row.get("fob_price") or price
            total = row.get("fob_total_usd") or row.get("fob_total") or total
        out.append(
            {
                "name": _safe_text(row.get("name")),
                "size": _safe_text(row.get("size")),
                "qty": _safe_text(row.get("qty")),
                "price": _safe_text(price),
                "total": _safe_text(total),
                "note": _safe_text(row.get("note"), ""),
            }
        )
    return out


def _pdf_lines(
    *,
    detail: dict[str, Any],
    prefill: dict[str, Any],
    bundle: dict[str, Any],
    export_lang: str,
    currency_mode: str,
) -> list[str]:
    meta = prefill.get("meta") if isinstance(prefill.get("meta"), dict) else {}
    title = "Formal Quote Sheet"
    lines = [
        title,
        f"Quote UID: {_safe_text(detail.get('quote_uid'))}",
        f"Calculation ID: {_safe_text(detail.get('calc_quote_id'))}",
        f"Version: {_safe_text(detail.get('version_no'))}",
        f"Language: {export_lang}",
        f"Currency mode: {currency_mode}",
        f"Customer: {_safe_text(meta.get('cust_name'))}",
        f"Contact: {_safe_text(meta.get('cust_contact'))}",
        f"Product: {_safe_text(detail.get('product_name') or prefill.get('product_name'))}",
        f"Quote date: {_safe_text(meta.get('quote_date_iso'))}",
        "",
        "Items:",
    ]
    for index, row in enumerate(_display_rows(bundle, export_lang, currency_mode), start=1):
        lines.append(
            f"{index}. {row['name']} | size {row['size']} | qty {row['qty']} | "
            f"price {row['price']} | total {row['total']}"
        )
        if row["note"]:
            lines.append(f"   note: {row['note']}")
    if len(lines) == 12:
        lines.append("No item rows available.")
    payee = bundle.get("payee") if isinstance(bundle.get("payee"), dict) else {}
    lines.extend(
        [
            "",
            "Payment:",
            f"Payee: {_safe_text(payee.get('company_name'))}",
            f"Account type: {_safe_text(payee.get('account_type'))}",
            "",
            "Generated from saved quote record. No quote recalculation was performed.",
        ]
    )
    return lines


def _generate_pdf(
    *,
    detail: dict[str, Any],
    prefill: dict[str, Any],
    bundle: dict[str, Any],
    export_lang: str,
    currency_mode: str,
) -> dict[str, Any]:
    QUOTE_EXPORT_PDF_DIR.mkdir(parents=True, exist_ok=True)
    quote_uid = _safe_text(detail.get("quote_uid"), "quote")
    version_no = _safe_text(detail.get("version_no"), "latest")
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    file_name = f"quote_sheet_{_safe_slug(quote_uid)}_v{_safe_slug(version_no)}_{stamp}.pdf"
    file_path = QUOTE_EXPORT_PDF_DIR / file_name

    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    c = canvas.Canvas(str(file_path), pagesize=A4)
    width, height = A4
    del width
    y = height - 48
    for index, line in enumerate(
        _pdf_lines(
            detail=detail,
            prefill=prefill,
            bundle=bundle,
            export_lang=export_lang,
            currency_mode=currency_mode,
        )
    ):
        if y < 48:
            c.showPage()
            y = height - 48
        c.setFont("STSong-Light", 16 if index == 0 else 10)
        c.drawString(48, y, line[:150])
        y -= 24 if index == 0 else 16
    c.save()
    size = file_path.stat().st_size
    return {
        "file_name": file_name,
        "file_path": str(file_path.resolve()),
        "download_url": f"/exports/quote_pdfs/{quote(file_name)}",
        "file_size": size,
    }


def _audit_record(
    user_context: dict[str, Any],
    query: dict[str, Any],
    result: dict[str, Any] | None = None,
    success: bool = False,
    error: str | None = None,
) -> dict[str, Any]:
    result_dict = result if isinstance(result, dict) else {}
    summary = result_dict.get("prefill_summary") if isinstance(result_dict.get("prefill_summary"), dict) else {}
    return {
        "tool": TOOL_NAME,
        "user_id": user_context.get("user_id"),
        "role": user_context.get("role", "guest"),
        "session_id": user_context.get("session_id"),
        "sales_user_id": user_context.get("sales_user_id"),
        "quote_uid": result_dict.get("quote_uid") or query.get("quote_uid") or "",
        "calc_quote_id": result_dict.get("calc_quote_id") or query.get("calc_quote_id") or "",
        "version_id": result_dict.get("version_id") or query.get("version_id"),
        "version_no": result_dict.get("version_no") or query.get("version_no"),
        "export_lang": result_dict.get("export_lang") or query.get("lang"),
        "currency_mode": result_dict.get("currency_mode") or query.get("currency_mode"),
        "dry_run": bool(result_dict.get("dry_run") or query.get("dry_run")),
        "item_count": summary.get("rows_count"),
        "file_name": result_dict.get("file_name"),
        "file_size": result_dict.get("file_size"),
        "success": success,
        "error": error,
    }


def _build_result(
    *,
    detail: dict[str, Any],
    prefill: dict[str, Any],
    export_lang: str,
    currency_mode: str,
    dry_run: bool,
) -> dict[str, Any]:
    bundle = _export_bundle(prefill, export_lang)
    validation = validate_quote_sheet_export_payload(export_lang=export_lang, bundle=bundle)
    missing_fields = _validation_missing_fields(validation)
    result = {
        "quote_uid": str(detail.get("quote_uid") or ""),
        "calc_quote_id": str(detail.get("calc_quote_id") or ""),
        "version_id": detail.get("version_id"),
        "version_no": detail.get("version_no"),
        "approval_status": _approval_status(detail),
        "approval_note": _approval_note(detail),
        "export_lang": export_lang,
        "currency_mode": currency_mode,
        "prefill_summary": _prefill_summary(prefill, detail),
    }
    if dry_run:
        result.update(
            {
                "dry_run": True,
                "can_export": _approval_status(detail) == "approved" and len(missing_fields) == 0,
                "missing_fields": missing_fields,
            }
        )
        return result
    if _approval_status(detail) != "approved":
        raise ValueError(_approval_block_message(detail))
    result.update(
        _generate_pdf(
            detail=detail,
            prefill=prefill,
            bundle=bundle,
            export_lang=export_lang,
            currency_mode=currency_mode,
        )
    )
    result["export_status"] = "generated"
    return result


def quote_export_pdf(input_data: dict) -> dict:
    user_context = normalize_user_context(
        input_data.get("user_context") if isinstance(input_data, dict) else {}
    )
    query: dict[str, Any] = {}
    result: dict[str, Any] | None = None
    try:
        require_tool_permission(user_context, TOOL_NAME)
        user_context, query = validate_quote_export_pdf_input(input_data)

        role = str(user_context.get("role") or "guest")
        sales_user_id = str(user_context.get("sales_user_id") or "").strip()
        if role == ROLE_SALES and not sales_user_id:
            raise ValueError("role=sales requires sales_user_id.")

        detail = _resolve_detail(query)
        if not detail:
            raise PermissionError(SAFE_NOT_FOUND)

        quote_uid = str(detail.get("quote_uid") or "").strip()
        if role == ROLE_SALES and not quote_upload_storage.sales_user_can_access_quote(quote_uid, sales_user_id):
            raise PermissionError(SAFE_NOT_FOUND)

        allow_admin = role in {ROLE_ADMIN, ROLE_SYSTEM_ADMIN}
        prefill = build_quote_sheet_prefill_payload_for_mcp(
            quote_uid,
            sales_user_id=sales_user_id,
            allow_admin=allow_admin,
            source=query["source"],
        )
        if not isinstance(prefill, dict) or not prefill.get("ok"):
            raise PermissionError(SAFE_NOT_FOUND)

        result = _build_result(
            detail=detail,
            prefill=prefill,
            export_lang=query["lang"],
            currency_mode=query["currency_mode"],
            dry_run=query["dry_run"],
        )
        write_audit_log(_audit_record(user_context, query, result=result, success=True))
        return {
            "ok": True,
            "tool": TOOL_NAME,
            "result": sanitize_quote_export_pdf_result(result, role),
        }
    except Exception as exc:  # noqa: BLE001
        error = SAFE_NOT_FOUND if isinstance(exc, PermissionError) and str(exc) == SAFE_NOT_FOUND else str(exc)
        try:
            write_audit_log(_audit_record(user_context, query, result=result, success=False, error=error))
        except Exception:
            pass
        return _failure(error)
