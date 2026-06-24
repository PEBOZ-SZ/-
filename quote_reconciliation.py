from __future__ import annotations

import re
from typing import Any

RECONCILIATION_CATEGORIES = (
    "主料",
    "里布",
    "拉链",
    "织带",
    "五金",
    "塑胶件",
    "Logo",
    "印刷",
    "车缝人工",
    "特殊工艺",
    "包装",
    "模具费",
    "模具摊销",
    "运费",
    "税费",
    "管理费",
    "毛利率",
    "EXW",
    "FOB",
    "最终单价",
)

DEFAULT_TOLERANCE_PCT = 3.0

_CATEGORY_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("主料", ("主料", "面料", "布料", "尼龙", "涤纶", "帆布", "fabric")),
    ("里布", ("里布", "内里", "lining")),
    ("拉链", ("拉链", "zipper")),
    ("织带", ("织带", "肩带", "绳带", "webbing", "strap")),
    ("五金", ("五金", "扣", "D环", "方扣", "插扣", "hook", "buckle")),
    ("塑胶件", ("塑胶", "胶件", "塑料", "plastic")),
    ("Logo", ("logo", "标", "织唛", "胶章", "吊牌")),
    ("印刷", ("印刷", "丝印", "热转印", "printing", "print")),
    ("车缝人工", ("车缝", "人工", "加工费", "sewing", "labor")),
    ("特殊工艺", ("特殊", "工艺", "压花", "滴胶", "电压", "绣花")),
    ("包装", ("包装", "纸箱", "opp", "胶袋", "箱", "packing", "package")),
    ("模具费", ("模具费", "开模")),
    ("模具摊销", ("模具摊销", "模具分摊", "mold share")),
    ("运费", ("运费", "运输", "freight", "shipping")),
    ("税费", ("税", "vat", "tax")),
    ("管理费", ("管理费", "杂费", "损耗", "overhead")),
)


def reconcile_quotes(
    manual_quote_result: dict[str, Any] | None,
    system_quote_result: dict[str, Any] | None,
    *,
    tolerance_pct: float = DEFAULT_TOLERANCE_PCT,
) -> dict[str, Any]:
    manual = _amounts_by_category(manual_quote_result or {})
    system = _amounts_by_category(system_quote_result or {})
    items = []
    within = True

    for category in RECONCILIATION_CATEGORIES:
        manual_amount = round(float(manual.get(category, 0.0)), 4)
        system_amount = round(float(system.get(category, 0.0)), 4)
        gap_amount = round(system_amount - manual_amount, 4)
        gap_pct = _gap_pct(manual_amount, system_amount)
        item_within = abs(gap_pct) <= float(tolerance_pct)
        if not item_within:
            within = False
        items.append(
            {
                "category": category,
                "manual_amount": manual_amount,
                "system_amount": system_amount,
                "gap_amount": gap_amount,
                "gap_pct": gap_pct,
                "within_tolerance": item_within,
                "reason_hint": _reason_hint(category, manual_amount, system_amount, gap_pct, tolerance_pct),
            }
        )

    total_gap_pct = _gap_pct(manual.get("最终单价", 0.0), system.get("最终单价", 0.0))
    if abs(total_gap_pct) > float(tolerance_pct):
        within = False

    blocking_reasons = _blocking_reasons(system_quote_result or {})
    if blocking_reasons:
        within = False

    return {
        "total_gap_pct": total_gap_pct,
        "within_tolerance": within,
        "items": items,
        "blocking_reasons": blocking_reasons,
    }


def _amounts_by_category(quote: dict[str, Any]) -> dict[str, float]:
    amounts = {category: 0.0 for category in RECONCILIATION_CATEGORIES}
    explicit = quote.get("reconciliation_items")
    if isinstance(explicit, dict):
        for key, value in explicit.items():
            category = _canonical_category(str(key or ""))
            if category:
                amounts[category] += _number(value)

    rows = quote.get("detail_rows")
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            category = _canonical_category(
                " ".join(
                    str(row.get(key) or "")
                    for key in ("category", "name", "spec", "calc_note", "calc_method")
                )
            )
            if category:
                amounts[category] += _number(row.get("amount"))

    settings = quote.get("settings") if isinstance(quote.get("settings"), dict) else {}
    amounts["模具费"] += _number(quote.get("mold_fee", settings.get("mold_fee")))
    amounts["管理费"] += _number(
        quote.get("system_overhead", settings.get("system_overhead", settings.get("system_overhead_config")))
    )
    amounts["毛利率"] += _number(quote.get("gross_margin_rate", settings.get("gross_margin_rate")))

    tiers = quote.get("tiers")
    tier0 = tiers[0] if isinstance(tiers, list) and tiers and isinstance(tiers[0], dict) else {}
    amounts["模具摊销"] += _number(tier0.get("mold_share"))
    amounts["税费"] += _number(tier0.get("taxed_price"))
    amounts["EXW"] += _number(tier0.get("exw_price"))
    amounts["FOB"] += _number(tier0.get("fob_price"))
    amounts["最终单价"] += _first_nonzero(
        _number(quote.get("final_unit_price")),
        _number(quote.get("unit_price")),
        _number(tier0.get("final_unit_price")),
        _number(tier0.get("fob_price")),
        _number(tier0.get("exw_price")),
    )

    return amounts


def _canonical_category(text: str) -> str:
    raw = str(text or "").strip()
    if raw in RECONCILIATION_CATEGORIES:
        return raw
    lowered = raw.lower()
    for category, patterns in _CATEGORY_PATTERNS:
        if any(pattern.lower() in lowered for pattern in patterns):
            return category
    return ""


def _blocking_reasons(system_quote: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    summary = system_quote.get("source_summary")
    if isinstance(summary, dict):
        if _number(summary.get("ai_estimate")) > 0:
            reasons.append("system_quote_result 存在 ai_estimate 金额来源，不能作为正式对账结果。")
        if _number(summary.get("default_demo")) > 0:
            reasons.append("system_quote_result 存在 default_demo 金额来源，不能作为正式对账结果。")

    rows = system_quote.get("detail_rows")
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict) or _number(row.get("amount")) == 0:
                continue
            source = str(row.get("source") or "").strip()
            if source in {"ai_estimate", "ai"} and not any("ai_estimate" in reason for reason in reasons):
                reasons.append("system_quote_result 存在 ai_estimate 金额来源，不能作为正式对账结果。")
            if source == "default_demo" and not any("default_demo" in reason for reason in reasons):
                reasons.append("system_quote_result 存在 default_demo 金额来源，不能作为正式对账结果。")
    return reasons


def _gap_pct(manual_amount: float, system_amount: float) -> float:
    if abs(manual_amount) < 1e-9:
        return 0.0 if abs(system_amount) < 1e-9 else 100.0
    return round((system_amount - manual_amount) / abs(manual_amount) * 100.0, 4)


def _reason_hint(
    category: str,
    manual_amount: float,
    system_amount: float,
    gap_pct: float,
    tolerance_pct: float,
) -> str:
    if manual_amount == 0 and system_amount == 0:
        return f"{category} 双方均未提供金额。"
    if abs(gap_pct) <= float(tolerance_pct):
        return f"{category} 差异在 ±{float(tolerance_pct):g}% 容差内。"
    direction = "高于" if gap_pct > 0 else "低于"
    return (
        f"{category} 系统金额{direction}人工金额 {abs(gap_pct):.2f}%，超过 "
        f"±{float(tolerance_pct):g}% 容差；请核对用量、单价、分摊或税费口径。"
    )


def _number(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return 0.0
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return 0.0
    try:
        return float(match.group(0))
    except (TypeError, ValueError):
        return 0.0


def _first_nonzero(*values: float) -> float:
    for value in values:
        if abs(value) > 1e-9:
            return value
    return 0.0
