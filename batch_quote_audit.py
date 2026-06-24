"""批量报价表计算一致性检查（只读、不改原表）。"""

from __future__ import annotations

import base64
import csv
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

AMOUNT_TOLERANCE = 0.02
TIER_TOLERANCE = 0.03

REFERENCE_YELLOW_GAP = 12.0
REFERENCE_YELLOW_PCT = 0.07
REFERENCE_RED_GAP = 25.0
REFERENCE_RED_PCT = 0.12

REFERENCE_TEXT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("system_cost_text", re.compile(r"系统(?:算出)?成本\s*[:：]?\s*([\d,.]+)\s*元?", re.I)),
    ("gpt_cost_text", re.compile(r"GPT(?:算出)?成本\s*[:：]?\s*([\d,.]+)\s*元?", re.I)),
    ("manual_cost_text", re.compile(r"人工(?:核算)?成本\s*[:：]?\s*([\d,.]+)\s*元?", re.I)),
    ("generic_cost_text", re.compile(r"成本(?:价)?\s*[:：]?\s*([\d,.]+)\s*元", re.I)),
)

SUMMARY_FIELDS = (
    "file_path",
    "file_name",
    "sheet_name",
    "product_name",
    "severity",
    "issue_count",
    "red_count",
    "yellow_count",
    "material_total",
    "default_quantity",
    "default_total_cost",
    "default_exw_price",
    "reference_cost",
    "cost_gap",
    "cost_gap_pct",
    "parse_path",
    "parse_error",
)

ISSUE_FIELDS = (
    "file_path",
    "file_name",
    "sheet_name",
    "product_name",
    "severity",
    "issue_code",
    "issue_message",
    "row_index",
    "material_name",
    "usage",
    "unit_price",
    "amount",
    "expected_amount",
    "suggestion",
)


@dataclass
class AuditIssue:
    file_path: str = ""
    file_name: str = ""
    sheet_name: str = ""
    product_name: str = ""
    severity: str = "yellow"
    issue_code: str = ""
    issue_message: str = ""
    row_index: int | None = None
    material_name: str = ""
    usage: str = ""
    unit_price: str = ""
    amount: float | None = None
    expected_amount: float | None = None
    suggestion: str = ""

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AuditSummary:
    file_path: str = ""
    file_name: str = ""
    sheet_name: str = ""
    product_name: str = ""
    severity: str = "green"
    issue_count: int = 0
    red_count: int = 0
    yellow_count: int = 0
    material_total: float | None = None
    default_quantity: int | None = None
    default_total_cost: float | None = None
    default_exw_price: float | None = None
    reference_cost: float | None = None
    cost_gap: float | None = None
    cost_gap_pct: float | None = None
    parse_path: str = ""
    parse_error: str = ""

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AuditResult:
    summary: AuditSummary
    issues: list[AuditIssue] = field(default_factory=list)


def _first_number(value: Any) -> float | None:
    from quote_engine import _first_number as _qe_first_number

    return _qe_first_number(value)


def _row_looks_valid_material(name: str) -> bool:
    n = str(name or "").strip()
    if not n:
        return False
    skip = ("物料合计", "系统成本", "单包系统成本", "合计", "小计", "汇总")
    return not any(k in n for k in skip)


def _usage_missing(usage_raw: Any) -> bool:
    u = str(usage_raw or "").strip()
    if u in {"", "-", "—"}:
        return True
    return _first_number(u) is None and not re.search(r"\d", u)


def _price_missing(price_raw: Any) -> bool:
    p = str(price_raw or "").strip()
    return p in {"", "-", "—", "无", "待定", "待填", "n/a", "na"}


def compute_expected_amount(usage_raw: Any, unit_price_raw: Any) -> float | None:
    from quote_engine import row_unit_alignment_hints

    usage = str(usage_raw or "").strip()
    price = str(unit_price_raw or "").strip()
    if _usage_missing(usage) or _price_missing(price):
        return None
    if row_unit_alignment_hints(usage, price):
        return None
    u = _first_number(usage)
    p = _first_number(price)
    if u is None or p is None:
        return None
    return round(u * p, 2)


def _issue(
    *,
    code: str,
    message: str,
    severity: str,
    suggestion: str = "",
    row_index: int | None = None,
    row: dict[str, Any] | None = None,
    expected_amount: float | None = None,
    meta: dict[str, Any] | None = None,
) -> AuditIssue:
    meta = meta or {}
    row = row or {}
    amount_raw = row.get("amount")
    try:
        amount_val = round(float(amount_raw), 2) if amount_raw not in (None, "") else None
    except (TypeError, ValueError):
        amount_val = None
    return AuditIssue(
        file_path=str(meta.get("file_path") or ""),
        file_name=str(meta.get("file_name") or ""),
        sheet_name=str(meta.get("sheet_name") or ""),
        product_name=str(meta.get("product_name") or ""),
        severity=severity,
        issue_code=code,
        issue_message=message,
        row_index=row_index,
        material_name=str(row.get("name") or ""),
        usage=str(row.get("usage") or ""),
        unit_price=str(row.get("unit_price") or ""),
        amount=amount_val,
        expected_amount=expected_amount,
        suggestion=suggestion,
    )


def audit_detail_rows(
    rows: list[dict[str, Any]],
    *,
    meta: dict[str, Any] | None = None,
) -> list[AuditIssue]:
    """行级检查：小计闭环、单位冲突、AI 估算、缺失字段。"""
    from quote_engine import row_amount_crosscheck_hint
    from quote_validation_gate import _row_unit_conflict_hints

    issues: list[AuditIssue] = []
    meta = meta or {}

    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not _row_looks_valid_material(name):
            continue

        conflict_hints = _row_unit_conflict_hints(row, row)
        if conflict_hints:
            issues.append(
                _issue(
                    code="unit_usage_price_conflict",
                    message="；".join(conflict_hints),
                    severity="red",
                    suggestion="核对用量单位与单价单位是否一致，必要时改为个/码/米等同维度计价。",
                    row_index=idx + 1,
                    row=row,
                    meta=meta,
                )
            )
            if bool(row.get("exclude_from_cost")):
                continue
            continue

        if bool(row.get("exclude_from_cost")):
            continue

        ai_flags = []
        if row.get("unit_price_ai"):
            ai_flags.append("单价AI")
        if row.get("usage_ai"):
            ai_flags.append("用量AI")
        if row.get("amount_ai"):
            ai_flags.append("小计AI")
        if row.get("pricing_review_required"):
            ai_flags.append("需核价")
        if str(row.get("recognition_status") or "").strip() == "candidate_review":
            ai_flags.append("候选待核")
        if ai_flags:
            issues.append(
                _issue(
                    code="ai_or_manual_review_required",
                    message=f"该行含 {'/'.join(ai_flags)} 标记",
                    severity="yellow",
                    suggestion="建议人工复核该行单价、用量与小计后再对外报价。",
                    row_index=idx + 1,
                    row=row,
                    meta=meta,
                )
            )

        usage = row.get("usage")
        unit_price = row.get("unit_price")
        try:
            amount = round(float(row.get("amount") or 0), 2)
        except (TypeError, ValueError):
            amount = 0.0

        expected = compute_expected_amount(usage, unit_price)
        if expected is not None:
            gap = abs(amount - expected)
            if gap > AMOUNT_TOLERANCE:
                cross_hint = row_amount_crosscheck_hint(usage, unit_price, amount)
                severity = "red" if gap > max(2.5, abs(amount or expected) * 0.12) else "yellow"
                msg = cross_hint or f"小计 {amount} 与 用量×单价 {expected} 不一致（差 {round(gap, 2)}）"
                issues.append(
                    _issue(
                        code="amount_usage_price_mismatch",
                        message=msg,
                        severity=severity,
                        suggestion="按用量×单价重算小计，或确认是否存在单位换算/组合计价。",
                        row_index=idx + 1,
                        row=row,
                        expected_amount=expected,
                        meta=meta,
                    )
                )
        else:
            if _usage_missing(usage) or _price_missing(unit_price):
                if amount <= AMOUNT_TOLERANCE and _row_looks_valid_material(name):
                    issues.append(
                        _issue(
                            code="missing_usage_or_price",
                            message="有效物料行缺少可解析的用量或单价",
                            severity="yellow",
                            suggestion="补齐用量/单价，或确认该行是否应参与报价。",
                            row_index=idx + 1,
                            row=row,
                            meta=meta,
                        )
                    )
            elif amount <= AMOUNT_TOLERANCE:
                issues.append(
                    _issue(
                        code="zero_amount_valid_material",
                        message="物料行小计为 0，但名称看起来有效",
                        severity="yellow",
                        suggestion="确认是否漏填用量/单价，或是否应排除该行。",
                        row_index=idx + 1,
                        row=row,
                        meta=meta,
                    )
                )

    return issues


def audit_tiers(result: dict[str, Any], payload: dict[str, Any] | None = None) -> list[AuditIssue]:
    """合计与阶梯公式闭环检查。"""
    issues: list[AuditIssue] = []
    payload = payload if isinstance(payload, dict) else {}
    meta = {
        "file_path": payload.get("_audit_file_path", ""),
        "file_name": payload.get("_audit_file_name", ""),
        "sheet_name": payload.get("_audit_sheet_name", ""),
        "product_name": str(result.get("product_name") or payload.get("product_name") or ""),
    }

    detail_rows = result.get("detail_rows") if isinstance(result.get("detail_rows"), list) else []
    material_total = result.get("material_total")
    try:
        material_total_f = round(float(material_total), 2)
    except (TypeError, ValueError):
        material_total_f = None

    detail_sum = 0.0
    for row in detail_rows:
        if not isinstance(row, dict):
            continue
        try:
            detail_sum += float(row.get("amount") or 0)
        except (TypeError, ValueError):
            pass
    detail_sum = round(detail_sum, 2)

    if material_total_f is not None and abs(material_total_f - detail_sum) > AMOUNT_TOLERANCE:
        issues.append(
            _issue(
                code="material_total_detail_sum_mismatch",
                message=(
                    f"material_total={material_total_f} 与 detail_rows 求和 {detail_sum} 不一致"
                ),
                severity="red",
                suggestion="检查明细行是否漏计/重复，或是否有行被 exclude_from_cost 排除。",
                meta=meta,
            )
        )

    summary_rows = result.get("summary_rows") if isinstance(result.get("summary_rows"), list) else []
    for sr in summary_rows:
        if not isinstance(sr, dict):
            continue
        if str(sr.get("name") or "").strip() != "物料合计":
            continue
        try:
            sr_amt = round(float(sr.get("amount") or 0), 2)
        except (TypeError, ValueError):
            continue
        if material_total_f is not None and abs(sr_amt - material_total_f) > AMOUNT_TOLERANCE:
            issues.append(
                _issue(
                    code="summary_material_total_mismatch",
                    message=f"summary_rows 物料合计 {sr_amt} 与 material_total {material_total_f} 不一致",
                    severity="red",
                    suggestion="核对 summary_rows 与 calculate_quote 输出是否同源。",
                    meta=meta,
                )
            )

    settings = result.get("settings") if isinstance(result.get("settings"), dict) else {}
    include_fob = bool(result.get("include_fob", settings.get("include_fob", True)))
    try:
        fob_add = float(settings.get("fob_addition_per_piece") or 0)
    except (TypeError, ValueError):
        fob_add = 0.0

    tiers = result.get("tiers") if isinstance(result.get("tiers"), list) else []
    for tier in tiers:
        if not isinstance(tier, dict):
            continue
        try:
            qty = int(tier.get("quantity") or 0)
        except (TypeError, ValueError):
            qty = 0
        if qty <= 0:
            continue
        try:
            total_cost = round(float(tier.get("total_cost") or 0), 2)
            cost_before = round(float(tier.get("cost_before_margin") or total_cost), 2)
            exw = round(float(tier.get("exw_price") or 0), 2)
            margin = float(tier.get("margin_rate") or 0)
            mold_share = round(float(tier.get("mold_share") or 0), 2)
            processing = round(float(tier.get("processing_fee") or settings.get("processing_fee") or 0), 2)
            overhead = round(float(tier.get("system_overhead_applied") or settings.get("system_overhead") or 0), 2)
        except (TypeError, ValueError):
            continue

        if material_total_f is not None:
            expected_cost = round(material_total_f + overhead + processing + mold_share, 2)
            if abs(total_cost - expected_cost) > TIER_TOLERANCE:
                issues.append(
                    _issue(
                        code="tier_total_cost_formula",
                        message=(
                            f"{qty}件 total_cost={total_cost}，期望 "
                            f"物料{material_total_f}+管理费{overhead}+加工{processing}+刀模摊{mold_share}={expected_cost}"
                        ),
                        severity="red",
                        suggestion="核对 total_cost 是否包含物料、管理费、加工费、刀模摊销。",
                        meta=meta,
                    )
                )

        if cost_before > 0 and margin < 1:
            expected_exw = round(cost_before / max(0.01, 1 - margin), 2)
            if abs(exw - expected_exw) > TIER_TOLERANCE:
                issues.append(
                    _issue(
                        code="tier_exw_margin_formula",
                        message=(
                            f"{qty}件 EXW={exw}，按 cost/(1-margin) 期望 {expected_exw}（margin={margin:.2%}）"
                        ),
                        severity="red",
                        suggestion="核对 EXW = total_cost / (1 - gross_margin_rate)。",
                        meta=meta,
                    )
                )

        if include_fob:
            try:
                fob = round(float(tier.get("fob_price") or 0), 2)
            except (TypeError, ValueError):
                fob = 0.0
            expected_fob = round(exw + fob_add, 2)
            if fob > 0 and abs(fob - expected_fob) > TIER_TOLERANCE:
                issues.append(
                    _issue(
                        code="tier_fob_formula",
                        message=f"{qty}件 FOB={fob}，期望 EXW+FOB附加={expected_fob}",
                        severity="red",
                        suggestion="核对 FOB = EXW + fob_addition_per_piece。",
                        meta=meta,
                    )
                )

        try:
            mold_fee = float(settings.get("mold_fee") or payload.get("mold_fee") or 0)
            expected_mold_share = round(mold_fee / qty, 2) if qty else 0.0
            if mold_fee > 0 and abs(mold_share - expected_mold_share) > TIER_TOLERANCE:
                issues.append(
                    _issue(
                        code="tier_mold_share",
                        message=f"{qty}件刀模摊 {mold_share} 与 mold_fee/qty={expected_mold_share} 不一致",
                        severity="red",
                        suggestion="核对刀模费是否按数量正确摊销。",
                        meta=meta,
                    )
                )
        except (TypeError, ValueError):
            pass

    return issues


def extract_reference_cost_anchors(
    source_context: dict[str, Any],
    result: dict[str, Any],
    payload: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """从 reference_prices 与表内文本提取成本参考锚点。"""
    anchors: list[dict[str, Any]] = []
    seen: set[tuple[str, float]] = set()
    payload = payload if isinstance(payload, dict) else {}

    for entry in payload.get("reference_prices") or []:
        if not isinstance(entry, dict):
            continue
        label = str(entry.get("kind") or entry.get("anchor_label") or "reference_prices").strip()
        val = entry.get("cost")
        if val is None:
            val = entry.get("material_subtotal")
        try:
            amount = round(float(val), 2)
        except (TypeError, ValueError):
            continue
        key = (label, amount)
        if key in seen:
            continue
        seen.add(key)
        compare = "total_cost"
        if entry.get("material_subtotal") is not None or "material" in label.lower():
            compare = "material_total"
        anchors.append(
            {
                "label": label or "reference_prices",
                "value": amount,
                "compare_target": compare,
                "source": "reference_prices",
            }
        )

    blob_parts: list[str] = []
    for row in source_context.get("scan_rows") or []:
        if not isinstance(row, list):
            continue
        for cell in row:
            text = str(cell or "").strip()
            if text:
                blob_parts.append(text)
    blob = "\n".join(blob_parts)

    for label, pattern in REFERENCE_TEXT_PATTERNS:
        for match in pattern.finditer(blob):
            try:
                amount = round(float(match.group(1).replace(",", "")), 2)
            except (TypeError, ValueError):
                continue
            key = (label, amount)
            if key in seen:
                continue
            seen.add(key)
            anchors.append(
                {
                    "label": label,
                    "value": amount,
                    "compare_target": "total_cost",
                    "source": "sheet_text",
                    "matched_text": match.group(0)[:120],
                }
            )

    default_tier = (result.get("tiers") or [{}])[0] if isinstance(result.get("tiers"), list) else {}
    return anchors


def _reference_gap_severity(gap: float, base: float) -> str:
    abs_gap = abs(gap)
    pct = abs_gap / abs(base) if base else 0.0
    if abs_gap > max(REFERENCE_RED_GAP, abs(base) * REFERENCE_RED_PCT):
        return "red"
    if abs_gap > max(REFERENCE_YELLOW_GAP, abs(base) * REFERENCE_YELLOW_PCT):
        return "yellow"
    return "green"


def audit_reference_costs(
    result: dict[str, Any],
    source_context: dict[str, Any],
    payload: dict[str, Any] | None = None,
    *,
    meta: dict[str, Any] | None = None,
) -> tuple[list[AuditIssue], float | None, float | None, float | None]:
    issues: list[AuditIssue] = []
    meta = meta or {}
    anchors = extract_reference_cost_anchors(source_context, result, payload)
    if not anchors:
        return issues, None, None, None

    material_total = result.get("material_total")
    tiers = result.get("tiers") if isinstance(result.get("tiers"), list) else []
    default_tier = tiers[0] if tiers else {}
    try:
        default_total_cost = round(float(default_tier.get("total_cost") or 0), 2)
    except (TypeError, ValueError):
        default_total_cost = None

    best_anchor = anchors[0]
    ref_val = float(best_anchor["value"])
    compare_key = str(best_anchor.get("compare_target") or "total_cost")
    if compare_key == "material_total":
        try:
            system_val = round(float(material_total), 2)
        except (TypeError, ValueError):
            system_val = None
    else:
        system_val = default_total_cost

    if system_val is None:
        return issues, ref_val, None, None

    gap = round(system_val - ref_val, 2)
    pct = round(gap / ref_val * 100, 2) if ref_val else None
    severity = _reference_gap_severity(gap, ref_val)
    if severity != "green":
        issues.append(
            _issue(
                code="reference_cost_gap",
                message=(
                    f"参考值 {ref_val}（{best_anchor.get('label')}） vs 系统值 {system_val}，"
                    f"差异 {gap}（{pct}%）"
                ),
                severity=severity,
                suggestion="对照表内手写成本/系统算出成本，确认物料、管理费、加工费、刀模摊销是否一致。",
                meta=meta,
            )
        )
    return issues, ref_val, gap, pct


def audit_quote_result(
    result: dict[str, Any],
    source_context: dict[str, Any],
    payload: dict[str, Any] | None = None,
) -> AuditResult:
    payload = payload if isinstance(payload, dict) else {}
    meta = {
        "file_path": str(source_context.get("file_path") or payload.get("_audit_file_path") or ""),
        "file_name": str(source_context.get("file_name") or payload.get("_audit_file_name") or ""),
        "sheet_name": str(source_context.get("sheet_name") or payload.get("_audit_sheet_name") or ""),
        "product_name": str(result.get("product_name") or payload.get("product_name") or ""),
    }

    issues: list[AuditIssue] = []
    source_rows = payload.get("items") if isinstance(payload.get("items"), list) else []
    detail_rows = result.get("detail_rows") if isinstance(result.get("detail_rows"), list) else []

    issues.extend(audit_detail_rows(source_rows, meta=meta))
    issues.extend(audit_detail_rows(detail_rows, meta=meta))
    issues.extend(audit_tiers(result, payload))
    ref_issues, ref_cost, cost_gap, cost_gap_pct = audit_reference_costs(
        result, source_context, payload, meta=meta
    )
    issues.extend(ref_issues)

    red_count = sum(1 for i in issues if i.severity == "red")
    yellow_count = sum(1 for i in issues if i.severity == "yellow")
    if red_count:
        severity = "red"
    elif yellow_count:
        severity = "yellow"
    else:
        severity = "green"

    tiers = result.get("tiers") if isinstance(result.get("tiers"), list) else []
    default_tier = tiers[0] if tiers else {}
    try:
        default_qty = int(default_tier.get("quantity") or 0) or None
    except (TypeError, ValueError):
        default_qty = None

    summary = AuditSummary(
        file_path=meta["file_path"],
        file_name=meta["file_name"],
        sheet_name=meta["sheet_name"],
        product_name=meta["product_name"],
        severity=severity,
        issue_count=len(issues),
        red_count=red_count,
        yellow_count=yellow_count,
        material_total=result.get("material_total"),
        default_quantity=default_qty,
        default_total_cost=default_tier.get("total_cost"),
        default_exw_price=default_tier.get("exw_price"),
        reference_cost=ref_cost,
        cost_gap=cost_gap,
        cost_gap_pct=cost_gap_pct,
        parse_path=str(source_context.get("parse_path") or ""),
        parse_error=str(source_context.get("parse_error") or ""),
    )
    return AuditResult(summary=summary, issues=issues)


def _payload_from_demand(demand: Any) -> dict[str, Any]:
    from demand_field_sources import material_row_source_type
    from demand_parser import compute_mold_fee_from_sections
    from price_kb import get_price_kb
    from price_source_resolver import PRICE_SOURCE_SHEET, has_business_unit_price
    from structure_usage import apply_structure_usage_hints, tighten_small_bag_usage_amounts

    kb = None
    try:
        kb = get_price_kb()
    except Exception:
        kb = None

    items: list[dict[str, Any]] = []
    for material in demand.materials:
        field_src = material_row_source_type(material.source, material.role)
        sheet_price = str(material.inline_price or "").strip()
        has_sheet_price = has_business_unit_price(sheet_price)
        row: dict[str, Any] = {
            "name": material.name,
            "role": material.role,
            "spec": material.spec or "-",
            "usage": "-",
            "unit_price": sheet_price if has_sheet_price else "-",
            "amount": 0.0,
            "kb_hit": False,
            "usage_ai": False,
            "unit_price_ai": not has_sheet_price,
            "amount_ai": False,
            "source": "ai" if not has_sheet_price else "kb",
            "demand_source": material.source,
            "field_source_type": field_src,
        }
        if has_sheet_price:
            row["price_source"] = PRICE_SOURCE_SHEET
        qu = str(getattr(material, "quoted_usage", "") or "").strip()
        if qu:
            row["usage"] = qu
            row["usage_ai"] = False
        if kb is not None and not has_sheet_price:
            hit = kb.lookup(material.name, material.spec or "")
            if hit:
                row["unit_price"] = hit.entry.raw_price
                row["kb_hit"] = True
                row["unit_price_ai"] = False
                row["source"] = "kb"
        items.append(row)

    structure_text = str(demand.structure_text or demand.structure_inference_text or "")
    apply_structure_usage_hints(items, structure_text, product_size=demand.product_size or {})
    tighten_small_bag_usage_amounts(
        items,
        product_size=demand.product_size or {},
        structure_text=structure_text,
    )

    payload: dict[str, Any] = {
        "items": items,
        "product_name": demand.product_name or demand.product_type or "",
        "mold_fee": float(compute_mold_fee_from_sections(demand.sections)),
        "include_fob": bool(demand.quote_settings.get("include_fob", True)),
        "reference_prices": list(demand.reference_prices or []),
        "structure_text": structure_text,
        "product_size": demand.product_size or {},
        "demand_template": bool(getattr(demand, "is_demand_template", True)),
    }
    qs = demand.quote_settings or {}
    if qs.get("processing_fee") is not None:
        payload["processing_fee"] = float(qs["processing_fee"])
    if qs.get("management_loss_rate") is not None:
        payload["management_loss_rate"] = float(qs["management_loss_rate"])
    if qs.get("system_overhead_fixed") is not None:
        payload["system_overhead_fixed"] = float(qs["system_overhead_fixed"])
    if qs.get("gross_margin_rate") is not None:
        payload["gross_margin_rate"] = float(qs["gross_margin_rate"])
    if demand.quantities:
        payload["quantities"] = list(demand.quantities)
    return payload


def _payload_from_simple_bom(parsed: Any) -> dict[str, Any]:
    from price_source_resolver import PRICE_SOURCE_SHEET, has_business_unit_price

    items: list[dict[str, Any]] = []
    for material in parsed.materials:
        unit_price_text = str(material.unit_price or "").strip()
        has_price = has_business_unit_price(unit_price_text)
        row: dict[str, Any] = {
            "name": material.name,
            "role": material.role,
            "spec": material.spec or "-",
            "usage": "-",
            "unit_price": unit_price_text if has_price else "-",
            "amount": 0.0,
            "unit_price_ai": not has_price,
            "amount_ai": False,
        }
        if has_price:
            row["price_source"] = PRICE_SOURCE_SHEET
        items.append(row)

    payload: dict[str, Any] = {
        "items": items,
        "product_name": parsed.product_name or "",
        "reference_prices": list(parsed.reference_prices or []),
        "product_size": parsed.product_size or {},
        "include_fob": True,
    }
    margin = parsed.quote_settings.get("gross_margin_rate")
    if margin is not None:
        payload["gross_margin_rate"] = margin
    if parsed.quote_settings.get("processing_fee") is not None:
        payload["processing_fee"] = float(parsed.quote_settings["processing_fee"])
    if parsed.quantities:
        payload["quantities"] = list(parsed.quantities)
    return payload


def _payload_from_sheet_parse(parsed: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "items": list(parsed.get("items") or []),
        "product_name": str(parsed.get("sheet_product_name") or ""),
        "quote_params": parsed.get("quote_params") or {},
        "include_fob": True,
    }
    qp = parsed.get("quote_params") if isinstance(parsed.get("quote_params"), dict) else {}
    qtys = qp.get("quantities") or qp.get("quantity_ladder")
    if isinstance(qtys, list) and qtys:
        payload["quantities"] = qtys
    return payload


def _scan_rows_for_context(file_path: Path) -> list[list[str]]:
    from sheet_parser import normalize_rows, parse_rows_from_bytes

    file_bytes = file_path.read_bytes()
    parsed, _ = parse_rows_from_bytes(file_name=file_path.name, file_bytes=file_bytes)
    return normalize_rows(parsed.rows)


def build_payload_from_xlsx(file_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """解析 xlsx 为 calculate_quote 所需 payload（只读）。"""
    from demand_parser import parse_demand_from_payload
    from sheet_parser import SheetParseError, parse_sheet_items_from_payload
    from simple_bom_parser import parse_simple_bom_from_payload

    context: dict[str, Any] = {
        "file_path": str(file_path.resolve()),
        "file_name": file_path.name,
        "sheet_name": "",
        "parse_path": "",
        "parse_error": "",
    }
    context["scan_rows"] = _scan_rows_for_context(file_path)

    b64 = base64.b64encode(file_path.read_bytes()).decode()
    uploaded_sheet = {"name": file_path.name, "content_base64": b64}

    try:
        demand = parse_demand_from_payload(uploaded_sheet)
        if demand.sections and demand.materials and len(demand.sections) >= 3:
            payload = _payload_from_demand(demand)
            context["parse_path"] = "demand_template"
            context["sheet_name"] = demand.sheet_name
            return payload, context
    except Exception:
        pass

    try:
        simple = parse_simple_bom_from_payload(uploaded_sheet)
        if simple.materials:
            payload = _payload_from_simple_bom(simple)
            context["parse_path"] = "simple_bom"
            context["sheet_name"] = simple.sheet_name
            return payload, context
    except Exception:
        pass

    parsed = parse_sheet_items_from_payload(uploaded_sheet)
    payload = _payload_from_sheet_parse(parsed)
    context["parse_path"] = "sheet_items"
    context["sheet_name"] = str(parsed.get("sheet_name") or "")
    return payload, context


def audit_xlsx_file(file_path: Path) -> AuditResult:
    """单文件：解析 → calculate_quote → 审计。"""
    from quote_engine import NoQuotableItemsError, calculate_quote

    context: dict[str, Any] = {
        "file_path": str(file_path.resolve()),
        "file_name": file_path.name,
        "sheet_name": "",
        "parse_path": "",
        "parse_error": "",
    }
    try:
        payload, ctx = build_payload_from_xlsx(file_path)
        context.update(ctx)
        payload["_audit_file_path"] = context["file_path"]
        payload["_audit_file_name"] = context["file_name"]
        payload["_audit_sheet_name"] = context["sheet_name"]
        result = calculate_quote(payload)
        return audit_quote_result(result, context, payload)
    except NoQuotableItemsError as exc:
        issue = _issue(
            code="parse_no_quotable_items",
            message=str(exc),
            severity="red",
            suggestion="补充可报价物料行的单价/用量，或确认表格是否被正确识别。",
            meta=context,
        )
        summary = AuditSummary(
            file_path=context["file_path"],
            file_name=context["file_name"],
            sheet_name=context["sheet_name"],
            severity="red",
            issue_count=1,
            red_count=1,
            parse_path=context.get("parse_path", ""),
            parse_error=str(exc),
        )
        return AuditResult(summary=summary, issues=[issue])
    except Exception as exc:
        issue = _issue(
            code="parse_failed",
            message=str(exc),
            severity="red",
            suggestion="检查表格格式是否为需求表/BOM/物料明细，或查看 parse_error 详情。",
            meta=context,
        )
        summary = AuditSummary(
            file_path=context["file_path"],
            file_name=context["file_name"],
            sheet_name=context["sheet_name"],
            severity="red",
            issue_count=1,
            red_count=1,
            parse_error=str(exc),
        )
        return AuditResult(summary=summary, issues=[issue])


def list_xlsx_files(input_dir: Path) -> list[Path]:
    if not input_dir.is_dir():
        return []
    return sorted(p for p in input_dir.iterdir() if p.is_file() and p.suffix.lower() == ".xlsx")


def batch_audit_directory(input_dir: Path) -> tuple[list[AuditSummary], list[AuditIssue]]:
    summaries: list[AuditSummary] = []
    issues: list[AuditIssue] = []
    for file_path in list_xlsx_files(input_dir):
        result = audit_xlsx_file(file_path)
        summaries.append(result.summary)
        issues.extend(result.issues)
    return summaries, issues


def write_audit_report(
    summaries: list[AuditSummary],
    issues: list[AuditIssue],
    output_path: Path,
    *,
    fmt: str = "xlsx",
) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fmt = str(fmt or "xlsx").strip().lower()
    if fmt == "csv":
        _write_csv_reports(output_path, summaries, issues)
        return output_path
    try:
        _write_xlsx_reports(output_path, summaries, issues)
        return output_path
    except Exception:
        csv_path = output_path.with_suffix(".csv")
        _write_csv_reports(csv_path, summaries, issues)
        return csv_path


def _write_csv_reports(output_path: Path, summaries: list[AuditSummary], issues: list[AuditIssue]) -> None:
    summary_path = output_path if output_path.suffix.lower() == ".csv" else output_path.with_name(output_path.stem + "_summary.csv")
    issues_path = summary_path.with_name(summary_path.stem.replace("_summary", "") + "_issues.csv")
    if issues_path == summary_path:
        issues_path = summary_path.with_name(summary_path.stem + "_issues.csv")

    with summary_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(SUMMARY_FIELDS))
        writer.writeheader()
        for item in summaries:
            writer.writerow({k: item.to_row().get(k, "") for k in SUMMARY_FIELDS})

    with issues_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(ISSUE_FIELDS))
        writer.writeheader()
        for item in issues:
            writer.writerow({k: item.to_row().get(k, "") for k in ISSUE_FIELDS})


def _write_xlsx_reports(output_path: Path, summaries: list[AuditSummary], issues: list[AuditIssue]) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws_summary = wb.active
    ws_summary.title = "Summary"
    ws_summary.append(list(SUMMARY_FIELDS))
    for item in summaries:
        row = item.to_row()
        ws_summary.append([row.get(k, "") for k in SUMMARY_FIELDS])

    ws_issues = wb.create_sheet("Issues")
    ws_issues.append(list(ISSUE_FIELDS))
    for item in issues:
        row = item.to_row()
        ws_issues.append([row.get(k, "") for k in ISSUE_FIELDS])

    wb.save(output_path)
