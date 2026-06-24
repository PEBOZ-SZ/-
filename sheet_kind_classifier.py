"""上传表格类型判定：客户需求表 vs 业务员 BOM / 报价结果 / 管理员修正。"""

from __future__ import annotations

import base64
import re
from typing import Any

from demand_parser import is_demand_template
from sheet_parser import (
    SheetParseError,
    normalize_text,
    parse_rows_from_bytes,
    row_get,
    row_looks_like_fixed_header,
)
from simple_bom_parser import is_simple_bom_template

KIND_CUSTOMER_DEMAND = "customer_demand"
KIND_SALES_BOM = "sales_bom"
KIND_QUOTE_OUTPUT = "quote_output"
KIND_ADMIN_CORRECTION = "admin_correction"
KIND_UNKNOWN = "unknown"

BLOCKED_KINDS = frozenset({KIND_SALES_BOM, KIND_QUOTE_OUTPUT, KIND_ADMIN_CORRECTION})

_SYSTEM_COLUMN_KEYWORDS = (
    "recognition_status",
    "pricing_review_required",
    "source_type",
    "usage_ai",
    "unit_price_ai",
    "amount_ai",
    "inferred_by_ai",
    "needs_human_confirm",
    "needs_manual_confirm",
    "field_source_type",
    "demand_source",
)

_ADMIN_TITLE_KEYWORDS = (
    "管理员修正",
    "修正bom",
    "修正 bom",
    "admin correction",
    "corrected bom",
)

_QUOTE_OUTPUT_KEYWORDS = (
    "报价单",
    "报价结果",
    "最终报价",
    "出厂价",
    "fob",
    "rmb/pc",
    "rmb/pcs",
    "成本核算",
    "成本明细",
    "利润",
    "毛利",
    "核算表",
    "quote output",
)

_SALES_BOM_SHEET_KEYWORDS = (
    "bom",
    "物料明细",
    "报价明细",
    "成本明细",
    "材料明细",
    "物料展开",
    "成本展开",
    "料单",
    "展开料",
)

# 标准客户需求模板 workbook 常见辅助 sheet，用于与业务员 BOM 区分。
_TEMPLATE_WORKBOOK_SHEET_KEYWORDS = (
    "字段映射",
    "json_key",
    "下拉选项",
    "使用说明",
    "材料明细补全说明",
    "需求表",
)

# 文件名中含以下片段时，「材料明细」等词不能单独视为 BOM 信号。
_AMBIGUOUS_BOM_FILENAME_RE = re.compile(
    r"材料明细(?:完善|补全)|报价资料\d",
    re.I,
)

_SALES_BOM_HEADER_KEYWORDS = (
    "物料名称",
    "材料名称",
    "规格",
    "用量",
    "单价",
    "小计",
    "金额",
    "成本",
    "报价",
)

_DEMAND_SHEET_KEYWORDS = (
    "需求表",
    "填写区",
    "业务报价",
    "客户需求",
)

_DEMAND_FIELD_KEYWORDS = (
    "产品信息",
    "产品名称",
    "产品类型",
    "外料",
    "里料",
    "工艺",
    "logo",
    "参考图片",
    "结构说明",
    "交期",
    "数量阶梯",
    "包装",
)

_SECTION_TITLE_RE = re.compile(r"^\s*([A-Ga-g])\s*[\.．、:：]\s*\S+")
_FORCE_CUSTOMER_DEMAND_RE = re.compile(
    r"(客户需求表|这是需求表|客户填的?需求|客户填写|需求填写|按需求表|标准需求表)",
    re.I,
)


def is_blocked_sheet_kind(kind: str) -> bool:
    return str(kind or "").strip() in BLOCKED_KINDS


def should_force_customer_demand_sheet(payload: dict[str, Any] | None, user_text: str = "") -> bool:
    if not isinstance(payload, dict):
        return False
    if _parse_boolish(payload.get("force_customer_demand")):
        return True
    text = " ".join(
        str(payload.get(k) or "").strip()
        for k in ("user_prompt", "prompt", "message")
    )
    text = f"{text} {str(user_text or '').strip()}".strip()
    return bool(_FORCE_CUSTOMER_DEMAND_RE.search(text))


def _parse_boolish(value: object) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "on"}


def _rows_from_uploaded_sheet(
    uploaded_sheet: dict[str, Any],
) -> tuple[str, str, list[list[str]], tuple[str, ...]]:
    file_name = str(uploaded_sheet.get("name") or "").strip()
    file_base64 = str(uploaded_sheet.get("content_base64") or "").strip()
    preferred_sheet = str(uploaded_sheet.get("sheet_name") or "").strip()
    if not file_name or not file_base64:
        raise SheetParseError("Missing file name or content.")
    file_bytes = base64.b64decode(file_base64, validate=True)
    parsed, _total = parse_rows_from_bytes(
        file_name=file_name,
        file_bytes=file_bytes,
        preferred_sheet=preferred_sheet,
    )
    workbook_sheets: tuple[str, ...] = ()
    if isinstance(parsed.sheet_row_counts, dict) and parsed.sheet_row_counts:
        workbook_sheets = tuple(str(name) for name in parsed.sheet_row_counts.keys())
    return file_name, parsed.sheet_name, parsed.rows, workbook_sheets


def _collect_header_blob(rows: list[list[str]], *, max_rows: int = 25) -> str:
    parts: list[str] = []
    for row in rows[:max_rows]:
        if not isinstance(row, list):
            continue
        for cell in row[:16]:
            text = str(cell or "").strip()
            if text:
                parts.append(text)
    return normalize_text(" ".join(parts))


def _row_keyword_hits(row: list[str], keywords: tuple[str, ...]) -> int:
    joined = normalize_text(" ".join(str(cell or "").strip() for cell in row[:20]))
    if not joined:
        return 0
    text = joined.lower()
    return sum(1 for kw in keywords if kw.lower() in text)


def _row_is_demand_material_detail_header(row: list[str]) -> bool:
    """C 区材料明细子表表头（类型/标准名/核算尺寸），不是业务员 BOM 表头。"""
    joined = normalize_text(" ".join(str(cell or "").strip() for cell in row[:16])).lower()
    if "类型" not in joined:
        return False
    has_std = any(
        token in joined
        for token in ("标准名/编码", "标准名", "名称/编码", "standard_name_code")
    )
    has_tail = any(token in joined for token in ("对应核算尺寸", "核算尺寸", "备注说明", "备注"))
    return bool(has_std and has_tail)


def _find_bom_detail_header_row(rows: list[list[str]], *, max_rows: int = 30) -> int | None:
    """定位含 BOM 明细列（物料/用量/单价/小计等）的表头行索引。"""
    pricing_keys = ("单价", "小计", "金额", "成本", "报价")
    for idx, row in enumerate(rows[:max_rows]):
        if not isinstance(row, list):
            continue
        if _row_is_demand_material_detail_header(row):
            continue
        hits = _row_keyword_hits(row, _SALES_BOM_HEADER_KEYWORDS)
        if hits < 4:
            continue
        joined = normalize_text(" ".join(str(cell or "").strip() for cell in row[:20])).lower()
        if not any(k in joined for k in pricing_keys):
            continue
        if "物料名称" in joined or "材料名称" in joined or "物料" in joined or "材料" in joined:
            return idx
        if hits >= 5:
            return idx
    return None


def _score_sales_bom_filename(name_blob: str, *, demand_template: bool, section_count: int) -> int:
    hits = _score_keywords(name_blob, _SALES_BOM_SHEET_KEYWORDS)
    if hits <= 0:
        return 0
    if demand_template and section_count >= 3 and _AMBIGUOUS_BOM_FILENAME_RE.search(name_blob):
        if "材料明细" in name_blob.lower():
            hits = max(0, hits - 1)
    return hits


def _is_strong_standard_customer_demand(
    *,
    demand_template: bool,
    section_count: int,
    name_blob: str,
    workbook_sheet_names: tuple[str, ...],
    system_cols: int,
    admin_title_hits: int,
    quote_markers: int,
) -> bool:
    """具备 A/B/C/D 需求模板结构时，优先视为客户需求表而非业务员 BOM。"""
    if not demand_template or section_count < 3:
        return False
    if system_cols >= 2 or admin_title_hits >= 1:
        return False
    if quote_markers >= 3:
        return False

    if _score_keywords(name_blob, _DEMAND_SHEET_KEYWORDS) >= 1:
        return True

    wb_blob = normalize_text(" ".join(workbook_sheet_names))
    wb_hits = _score_keywords(wb_blob, _TEMPLATE_WORKBOOK_SHEET_KEYWORDS)
    if wb_hits >= 2:
        return True
    if "需求表" in wb_blob and ("字段映射" in wb_blob or "下拉选项" in wb_blob):
        return True

    if section_count >= 4:
        return True
    return False


def _has_system_export_features(
    *,
    system_cols: int,
    bom_header_idx: int | None,
    quote_markers: int,
    admin_title_hits: int,
) -> bool:
    if system_cols >= 2:
        return True
    if system_cols >= 1 and (bom_header_idx is not None or quote_markers >= 1 or admin_title_hits >= 1):
        return True
    if admin_title_hits >= 1 and bom_header_idx is not None:
        return True
    return False


def _has_quote_output_features(*, quote_markers: int, all_blob: str, bom_header_idx: int | None) -> bool:
    if quote_markers >= 2:
        return True
    if quote_markers >= 1 and bom_header_idx is not None:
        return True
    compact = all_blob.lower()
    if quote_markers >= 1 and any(k in compact for k in ("成本价", "最终报价", "出厂价", "fob")):
        return True
    return False


def _has_sales_bom_features(
    *,
    rows: list[list[str]],
    bom_header_idx: int | None,
    sheet_bom_hits: int,
    all_blob: str,
    strong_demand: bool = False,
    demand_template: bool = False,
    section_count: int = 0,
) -> bool:
    if strong_demand:
        return False
    if demand_template and section_count >= 3:
        # 需求模板 C 区可能含用量/单价列，仅凭表头不足以判定为业务员 BOM。
        if _score_keywords(all_blob[:800], ("物料合计", "材料合计", "ai算出成本")) >= 2:
            return True
        if _score_keywords(all_blob[:800], ("最终报价", "成本价")) >= 2 and bom_header_idx is not None:
            return True
        return False
    if is_simple_bom_template(rows):
        return True
    if bom_header_idx is not None:
        return True
    if sheet_bom_hits >= 1 and bom_header_idx is not None:
        return True
    if row_looks_like_fixed_header(rows[0] if rows else []) or any(
        row_looks_like_fixed_header(row) for row in rows[:8]
    ):
        if _score_keywords(_collect_header_blob(rows, max_rows=8), _SALES_BOM_HEADER_KEYWORDS) >= 4:
            return True
    if _score_keywords(all_blob[:800], ("物料合计", "材料合计", "成本价", "最终报价", "ai算出成本")) >= 2:
        return True
    return False


def _is_pure_customer_demand_layout(
    *,
    section_count: int,
    demand_template: bool,
    system_cols: int,
    quote_markers: int,
    bom_header_idx: int | None,
    admin_title_hits: int,
) -> bool:
    if system_cols > 0 or quote_markers >= 2 or bom_header_idx is not None or admin_title_hits >= 1:
        return False
    if section_count >= 3:
        return True
    return bool(demand_template and section_count >= 2)


def _pick_system_export_kind(
    scores: dict[str, int],
    *,
    quote_markers: int,
    admin_title_hits: int,
    bom_header_idx: int | None,
) -> str:
    if admin_title_hits >= 1 or scores[KIND_ADMIN_CORRECTION] >= scores[KIND_QUOTE_OUTPUT] + 2:
        return KIND_ADMIN_CORRECTION
    if quote_markers >= 2 and scores[KIND_QUOTE_OUTPUT] >= scores[KIND_ADMIN_CORRECTION]:
        if bom_header_idx is not None and scores[KIND_ADMIN_CORRECTION] >= 4:
            return KIND_ADMIN_CORRECTION
        return KIND_QUOTE_OUTPUT
    blocked = (
        (KIND_ADMIN_CORRECTION, scores[KIND_ADMIN_CORRECTION]),
        (KIND_QUOTE_OUTPUT, scores[KIND_QUOTE_OUTPUT]),
        (KIND_SALES_BOM, scores[KIND_SALES_BOM]),
    )
    blocked.sort(key=lambda item: item[1], reverse=True)
    return blocked[0][0] if blocked[0][1] > 0 else KIND_ADMIN_CORRECTION


def _count_titled_section_markers(rows: list[list[str]]) -> int:
    seen: set[str] = set()
    for row in rows[:60]:
        first = row_get(row, 0).strip()
        match = _SECTION_TITLE_RE.match(first)
        if not match:
            continue
        seen.add(match.group(1).upper())
    return len(seen)


def _sheet_name_blob(file_name: str, sheet_name: str) -> str:
    return normalize_text(f"{file_name} {sheet_name}")


def _score_system_columns(header_blob: str) -> int:
    blob = header_blob.lower()
    return sum(1 for kw in _SYSTEM_COLUMN_KEYWORDS if kw.lower() in blob)


def _score_keywords(blob: str, keywords: tuple[str, ...]) -> int:
    text = blob.lower()
    return sum(1 for kw in keywords if kw.lower() in text)


def classify_uploaded_sheet_kind(
    uploaded_sheet: dict[str, Any],
    *,
    user_text: str = "",
) -> tuple[str, dict[str, Any]]:
    """返回 (kind, detail)。kind 为 customer_demand / sales_bom / quote_output / admin_correction / unknown。"""
    detail: dict[str, Any] = {
        "file_name": "",
        "sheet_name": "",
        "reasons": [],
        "scores": {},
    }
    if not isinstance(uploaded_sheet, dict):
        return KIND_UNKNOWN, {**detail, "reasons": ["empty_payload"]}

    try:
        file_name, sheet_name, rows, workbook_sheet_names = _rows_from_uploaded_sheet(uploaded_sheet)
    except Exception as exc:  # noqa: BLE001
        return KIND_UNKNOWN, {**detail, "reasons": [f"decode_failed:{exc}"]}

    detail["file_name"] = file_name
    detail["sheet_name"] = sheet_name
    if not rows:
        return KIND_UNKNOWN, {**detail, "reasons": ["empty_rows"]}

    header_blob = _collect_header_blob(rows)
    all_blob = normalize_text(
        " ".join(
            str(cell or "").strip()
            for row in rows[:80]
            for cell in (row if isinstance(row, list) else [])[:12]
        )
    )
    name_blob = _sheet_name_blob(file_name, sheet_name)
    section_count = _count_titled_section_markers(rows)
    demand_template = is_demand_template(rows)
    bom_header_idx = _find_bom_detail_header_row(rows)
    admin_title_hits = _score_keywords(name_blob + " " + all_blob[:400], _ADMIN_TITLE_KEYWORDS)
    quote_markers = _score_keywords(name_blob + " " + all_blob[:1200], _QUOTE_OUTPUT_KEYWORDS)

    scores = {
        KIND_ADMIN_CORRECTION: 0,
        KIND_QUOTE_OUTPUT: 0,
        KIND_SALES_BOM: 0,
        KIND_CUSTOMER_DEMAND: 0,
    }
    reasons: list[str] = []

    system_cols = _score_system_columns(header_blob)
    if system_cols >= 2:
        scores[KIND_ADMIN_CORRECTION] += 6 + system_cols
        reasons.append(f"system_columns={system_cols}")
    if admin_title_hits >= 1:
        scores[KIND_ADMIN_CORRECTION] += 5
        reasons.append("admin_title")

    if quote_markers >= 2:
        scores[KIND_QUOTE_OUTPUT] += 4 + quote_markers
        reasons.append(f"quote_output_keywords={quote_markers}")
    elif quote_markers == 1 and system_cols >= 1:
        scores[KIND_QUOTE_OUTPUT] += 3
        reasons.append("quote_output_with_system_cols")
    if bom_header_idx is not None:
        scores[KIND_SALES_BOM] += 5
        scores[KIND_ADMIN_CORRECTION] += 2
        reasons.append(f"bom_detail_header_row={bom_header_idx}")

    if is_simple_bom_template(rows):
        scores[KIND_SALES_BOM] += 6
        reasons.append("simple_bom_template")
    if row_looks_like_fixed_header(rows[0] if rows else []) or any(
        row_looks_like_fixed_header(row) for row in rows[:8]
    ):
        header_hits = _score_keywords(header_blob, _SALES_BOM_HEADER_KEYWORDS)
        if header_hits >= 3:
            scores[KIND_SALES_BOM] += 4 + header_hits
            reasons.append(f"fixed_bom_header={header_hits}")
    sheet_bom_hits = _score_sales_bom_filename(
        name_blob,
        demand_template=demand_template,
        section_count=section_count,
    )
    if sheet_bom_hits >= 1:
        scores[KIND_SALES_BOM] += 3 + sheet_bom_hits
        reasons.append(f"sheet_bom_name={sheet_bom_hits}")
    if _score_keywords(all_blob[:800], ("物料合计", "材料合计", "成本价", "最终报价", "ai算出成本")) >= 2:
        scores[KIND_SALES_BOM] += 2
        reasons.append("sales_reference_prices")

    demand_name_hits = _score_keywords(name_blob, _DEMAND_SHEET_KEYWORDS)
    demand_field_hits = _score_keywords(all_blob[:1200], _DEMAND_FIELD_KEYWORDS)
    if demand_template:
        scores[KIND_CUSTOMER_DEMAND] += 4
        reasons.append("demand_template")
    if section_count >= 3:
        scores[KIND_CUSTOMER_DEMAND] += 5 + section_count
        reasons.append(f"section_markers={section_count}")
    elif section_count >= 2:
        scores[KIND_CUSTOMER_DEMAND] += 2 + section_count
        reasons.append(f"section_markers={section_count}")
    if demand_name_hits >= 1:
        scores[KIND_CUSTOMER_DEMAND] += 3 + demand_name_hits
        reasons.append(f"demand_sheet_name={demand_name_hits}")
    if demand_field_hits >= 3 and section_count >= 2:
        scores[KIND_CUSTOMER_DEMAND] += 2 + demand_field_hits // 2
        reasons.append(f"demand_fields={demand_field_hits}")

    detail["scores"] = scores
    detail["reasons"] = reasons
    detail["section_count"] = section_count
    detail["demand_template"] = demand_template
    detail["system_column_hits"] = system_cols
    detail["quote_marker_hits"] = quote_markers
    detail["bom_header_row"] = bom_header_idx
    detail["admin_title_hits"] = admin_title_hits
    detail["workbook_sheet_names"] = list(workbook_sheet_names)

    strong_demand = _is_strong_standard_customer_demand(
        demand_template=demand_template,
        section_count=section_count,
        name_blob=name_blob,
        workbook_sheet_names=workbook_sheet_names,
        system_cols=system_cols,
        admin_title_hits=admin_title_hits,
        quote_markers=quote_markers,
    )
    detail["strong_customer_demand"] = strong_demand

    # --- 决策：系统导出仍优先；标准需求模板优先于业务员 BOM 误判 ---
    if _has_system_export_features(
        system_cols=system_cols,
        bom_header_idx=bom_header_idx,
        quote_markers=quote_markers,
        admin_title_hits=admin_title_hits,
    ):
        kind = _pick_system_export_kind(
            scores,
            quote_markers=quote_markers,
            admin_title_hits=admin_title_hits,
            bom_header_idx=bom_header_idx,
        )
        detail["decision"] = "blocked_system_export_priority"
        return kind, detail

    if strong_demand:
        detail["decision"] = "customer_demand_strong_template"
        return KIND_CUSTOMER_DEMAND, detail

    if _has_quote_output_features(
        quote_markers=quote_markers,
        all_blob=all_blob,
        bom_header_idx=bom_header_idx,
    ):
        detail["decision"] = "blocked_quote_output_priority"
        return KIND_QUOTE_OUTPUT, detail

    if _has_sales_bom_features(
        rows=rows,
        bom_header_idx=bom_header_idx,
        sheet_bom_hits=sheet_bom_hits,
        all_blob=all_blob,
        strong_demand=strong_demand,
        demand_template=demand_template,
        section_count=section_count,
    ):
        detail["decision"] = "blocked_sales_bom_priority"
        return KIND_SALES_BOM, detail

    if _is_pure_customer_demand_layout(
        section_count=section_count,
        demand_template=demand_template,
        system_cols=system_cols,
        quote_markers=quote_markers,
        bom_header_idx=bom_header_idx,
        admin_title_hits=admin_title_hits,
    ):
        detail["decision"] = "customer_demand_layout"
        return KIND_CUSTOMER_DEMAND, detail

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    best_kind, best_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0

    if best_score <= 0:
        detail["decision"] = "unknown_no_signal"
        return KIND_UNKNOWN, detail

    if best_kind == KIND_CUSTOMER_DEMAND and best_score >= 4 and best_score > second_score:
        detail["decision"] = "customer_demand_score"
        return KIND_CUSTOMER_DEMAND, detail

    if best_kind in BLOCKED_KINDS and best_score >= 4 and best_score >= second_score:
        detail["decision"] = "blocked_score_fallback"
        return best_kind, detail

    detail["decision"] = "unknown_ambiguous"
    return KIND_UNKNOWN, detail


def _blocked_message(kind: str, detail: dict[str, Any]) -> str:
    file_name = str(detail.get("file_name") or "上传表格").strip() or "上传表格"
    if kind == KIND_SALES_BOM:
        return (
            f"检测到上传的是业务员 BOM/报价明细表（{file_name}），已作为参考附件保留，"
            "不会当作客户需求重新识别。如需报价，请上传标准客户需求表，或在消息中说明「这是客户需求表」。"
        )
    if kind == KIND_QUOTE_OUTPUT:
        return (
            f"检测到上传的是报价结果/核算表（{file_name}），已作为参考附件保留，"
            "不会进入客户需求解析或重新生成 BOM。"
        )
    if kind == KIND_ADMIN_CORRECTION:
        return (
            f"检测到上传的是管理员修正 BOM/系统报价表（{file_name}），已作为参考附件保留，"
            "不会覆盖当前客户需求或再次参与自动报价。"
        )
    return (
        f"检测到上传表格（{file_name}）不适合作为客户需求自动识别，已仅作参考保留。"
    )


def build_sheet_kind_blocked_response(kind: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    detail = detail if isinstance(detail, dict) else {}
    return {
        "quote_ready": False,
        "reply_type": "upload_sheet_kind_blocked",
        "assistant_message": _blocked_message(kind, detail),
        "upload_sheet_kind": kind,
        "upload_sheet_reference_only": True,
        "upload_sheet_kind_detail": detail,
        "intent": "upload_sheet_reference",
    }


def build_sheet_kind_unknown_response(detail: dict[str, Any] | None = None) -> dict[str, Any]:
    detail = detail if isinstance(detail, dict) else {}
    file_name = str(detail.get("file_name") or "上传表格").strip() or "上传表格"
    return {
        "quote_ready": False,
        "reply_type": "upload_sheet_kind_unknown",
        "assistant_message": (
            f"无法确认 {file_name} 是「客户需求表」还是「业务员 BOM/报价明细表」。"
            "为避免误识别导致重复物料，本轮不会自动报价。"
            "请补充说明表格类型；若为客户需求表，请在消息中写明「这是客户需求表」后重新发送。"
        ),
        "upload_sheet_kind": KIND_UNKNOWN,
        "upload_sheet_reference_only": True,
        "upload_sheet_kind_detail": detail,
        "intent": "upload_sheet_clarify",
    }
