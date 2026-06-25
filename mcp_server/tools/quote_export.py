from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp_server.audit import write_audit_log
from mcp_server.auth import require_tool_permission
from mcp_server.sanitizer import sanitize_quote_export_result
from mcp_server.schemas import normalize_user_context, validate_quote_export_input
from mcp_server.tools.quote_save import QUOTE_SAVE_STORE_PATH


TOOL_NAME = "quote_export"
QUOTE_EXPORT_DIR = Path("exports")


def _load_saved_quote(quote_id: str) -> dict[str, Any]:
    if not QUOTE_SAVE_STORE_PATH.exists():
        raise FileNotFoundError(f"quote_id 不存在：{quote_id}")
    for line in QUOTE_SAVE_STORE_PATH.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            record = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and str(record.get("quote_id") or "") == quote_id:
            return record
    raise FileNotFoundError(f"quote_id 不存在：{quote_id}")


def _safe_text(value: Any) -> str:
    text = str(value if value is not None else "").strip()
    return text or "-"


def _quote_lines(record: dict[str, Any]) -> list[str]:
    quote = record.get("quote_result") if isinstance(record.get("quote_result"), dict) else {}
    lines = [
        "正式报价单",
        f"报价编号: {_safe_text(record.get('quote_id'))}",
        f"生成时间: {_safe_text(record.get('created_at'))}",
        f"产品名称: {_safe_text(quote.get('product_name'))}",
        "",
        "数量档:",
    ]
    tiers = quote.get("tiers")
    if isinstance(tiers, list) and tiers:
        for tier in tiers:
            if not isinstance(tier, dict):
                continue
            bits = [
                f"数量 {_safe_text(tier.get('quantity'))}",
                f"EXW {_safe_text(tier.get('exw_price'))}",
                f"FOB {_safe_text(tier.get('fob_price'))}",
                f"加工费 {_safe_text(tier.get('processing_fee'))}",
            ]
            lines.append(" - " + " | ".join(bits))
    else:
        lines.append(" - 无数量档")

    lines.extend(["", "材料信息:"])
    items = quote.get("items")
    if isinstance(items, list) and items:
        for item in items:
            if not isinstance(item, dict):
                continue
            bits = [
                _safe_text(item.get("name")),
                f"规格 {_safe_text(item.get('spec'))}",
                f"用量 {_safe_text(item.get('usage'))}",
                f"单价 {_safe_text(item.get('unit_price'))}",
                f"小计 {_safe_text(item.get('amount'))}",
            ]
            lines.append(" - " + " | ".join(bits))
    else:
        lines.append(" - 无材料明细")

    total = quote.get("total_price")
    if total is not None:
        lines.extend(["", f"总价: {_safe_text(total)}"])
    return lines


def _export_pdf(record: dict[str, Any], export_dir: Path = QUOTE_EXPORT_DIR) -> dict[str, Any]:
    quote_id = str(record.get("quote_id") or "").strip()
    if not quote_id:
        raise ValueError("保存记录缺少 quote_id。")
    export_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"报价单_{quote_id}.pdf"
    file_path = export_dir / file_name

    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    c = canvas.Canvas(str(file_path), pagesize=A4)
    width, height = A4
    y = height - 48
    c.setFont("STSong-Light", 16)
    for index, line in enumerate(_quote_lines(record)):
        if y < 48:
            c.showPage()
            c.setFont("STSong-Light", 12)
            y = height - 48
        c.setFont("STSong-Light", 16 if index == 0 else 11)
        c.drawString(48, y, line[:120])
        y -= 24 if index == 0 else 18
    c.setFont("STSong-Light", 9)
    c.drawString(48, 28, "本文件由 MCP quote_export 从已保存报价生成，未重新计算报价。")
    c.save()

    return {
        "quote_id": quote_id,
        "file_type": "pdf",
        "file_path": str(file_path.resolve()),
        "file_name": file_name,
        "created_at": datetime.now().isoformat(),
    }


def _audit_record(
    user_context: dict[str, Any],
    quote_id: str,
    file_type: str = "pdf",
    success: bool = False,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "tool": TOOL_NAME,
        "user_id": user_context.get("user_id"),
        "role": user_context.get("role", "guest"),
        "session_id": user_context.get("session_id"),
        "quote_id": quote_id,
        "file_type": file_type,
        "success": success,
        "error": error,
    }


def _failure(error: str) -> dict[str, Any]:
    return {
        "ok": False,
        "tool": TOOL_NAME,
        "error": error,
    }


def quote_export(input_data: dict) -> dict:
    user_context = normalize_user_context(
        input_data.get("user_context") if isinstance(input_data, dict) else {}
    )
    quote_id = ""
    try:
        require_tool_permission(user_context, TOOL_NAME)
        user_context, query = validate_quote_export_input(input_data)
        quote_id = query["quote_id"]
        record = _load_saved_quote(quote_id)
        result = _export_pdf(record, QUOTE_EXPORT_DIR)
        write_audit_log(_audit_record(user_context, quote_id, result["file_type"], success=True))
        return {
            "ok": True,
            "tool": TOOL_NAME,
            "result": sanitize_quote_export_result(result, user_context.get("role", "sales")),
        }
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
        try:
            write_audit_log(_audit_record(user_context, quote_id, success=False, error=error))
        except Exception:
            pass
        return _failure(error)
