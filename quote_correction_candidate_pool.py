"""报价纠错候选池、错误归因、审核与规则晋升（SQLite，复用 quote_correction_learning 连接）。"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from quote_correction_learning import (
    APPLY_CONFIDENCE_MIN,
    LEARNED_RULE_ID_PREFIX,
    RULE_SOURCE_ADMIN_APPROVED,
    RULE_STATUS_APPROVED,
    RULE_STATUS_PENDING,
    RULE_STATUS_REJECTED,
    TRACK_FIELDS,
    _connect,
    _json_list,
    _material_category_key,
    _matches_keywords,
    _norm_value,
    _structure_blob,
    _utc_now_iso,
    ensure_correction_tables,
    init_correction_learning_storage,
    set_test_connection,
)

logger = logging.getLogger(__name__)

CANDIDATE_STATUS_PENDING = "pending"
CANDIDATE_STATUS_APPROVED = "approved"
CANDIDATE_STATUS_REJECTED = "rejected"
# 兼容旧数据读取；新写入批准状态统一为 approved
CANDIDATE_STATUS_APPLIED = "applied"

ERROR_TYPES = (
    "usage_overestimated",
    "usage_underestimated",
    "unit_price_wrong",
    "unit_mismatch",
    "missing_material",
    "extra_material",
    "amount_mismatch",
    "processing_fee_wrong",
    "margin_or_quote_formula_wrong",
    "packaging_wrong",
    "unknown",
)


def ensure_candidate_tables(conn) -> None:
    ensure_correction_tables(conn)


def _first_number(value: Any) -> float | None:
    from quote_engine import _first_number as qe_first

    return qe_first(value)


def _parse_amount(row: dict[str, Any]) -> float:
    try:
        return round(float(row.get("amount") or 0), 4)
    except (TypeError, ValueError):
        return 0.0


def _pct_diff(old: float, new: float) -> float | None:
    if old <= 0 and new <= 0:
        return None
    base = old if old > 0 else new
    return abs(new - old) / base


def _classification(
    error_type: str,
    *,
    confidence: float = 0.75,
    reason: str = "",
    evidence: dict[str, Any] | None = None,
    suggested_rule: dict[str, Any] | None = None,
) -> dict[str, Any]:
    et = error_type if error_type in ERROR_TYPES else "unknown"
    return {
        "error_type": et,
        "confidence": round(float(confidence), 3),
        "reason": str(reason or "").strip(),
        "evidence": evidence if isinstance(evidence, dict) else {},
        "suggested_rule": suggested_rule if isinstance(suggested_rule, dict) else {},
    }


def classify_correction_error(
    old_row: dict[str, Any],
    new_row: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """对比单行修正，返回 error_type / confidence / reason / evidence / suggested_rule。"""
    from quote_engine import row_unit_alignment_hints

    context = context if isinstance(context, dict) else {}
    old_row = old_row if isinstance(old_row, dict) else {}
    new_row = new_row if isinstance(new_row, dict) else {}

    material_name = str(new_row.get("name") or old_row.get("name") or "").strip()
    old_usage = str(old_row.get("usage") or "").strip()
    new_usage = str(new_row.get("usage") or "").strip()
    old_price = str(old_row.get("unit_price") or "").strip()
    new_price = str(new_row.get("unit_price") or "").strip()
    old_amt = _parse_amount(old_row)
    new_amt = _parse_amount(new_row)

    evidence = {
        "material_name": material_name,
        "old_usage": old_usage,
        "new_usage": new_usage,
        "old_unit_price": old_price,
        "new_unit_price": new_price,
        "old_amount": old_amt,
        "new_amount": new_amt,
        "product_name": str(context.get("product_name") or ""),
        "structure_text": _structure_blob(context)[:300],
    }

    old_present = bool(material_name) and (
        old_amt > 0 or old_usage not in {"", "-", "—"} or old_price not in {"", "-", "—"}
    )
    new_present = bool(material_name) and (
        new_amt > 0 or new_usage not in {"", "-", "—"} or new_price not in {"", "-", "—"}
    )

    if material_name and not old_present and new_present:
        return _classification(
            "missing_material",
            confidence=0.9,
            reason=f"新增材料行：{material_name}",
            evidence=evidence,
        )
    if material_name and old_present and not new_present:
        return _classification(
            "extra_material",
            confidence=0.9,
            reason=f"删除或清零材料：{material_name}",
            evidence=evidence,
        )
    if material_name and old_present and new_present and new_amt <= 0 and old_amt > 0:
        return _classification(
            "extra_material",
            confidence=0.85,
            reason=f"材料 {material_name} 修正后金额为 0",
            evidence=evidence,
        )

    usage_for_conflict = new_usage or old_usage
    price_for_conflict = new_price or old_price
    if usage_for_conflict and price_for_conflict:
        if row_unit_alignment_hints(usage_for_conflict, price_for_conflict):
            return _classification(
                "unit_mismatch",
                confidence=0.92,
                reason=f"用量单位与单价单位维度冲突：{usage_for_conflict} vs {price_for_conflict}",
                evidence=evidence,
            )

    ou = _first_number(old_usage)
    nu = _first_number(new_usage)
    op = _first_number(old_price)
    np = _first_number(new_price)

    usage_changed = ou is not None and nu is not None and abs(ou - nu) > 1e-6
    price_changed = op is not None and np is not None and abs(op - np) > 1e-6
    usage_pct = _pct_diff(ou or 0, nu or 0) if usage_changed else None
    price_pct = _pct_diff(op or 0, np or 0) if price_changed else None

    usage_close = usage_pct is None or usage_pct <= 0.15
    price_close = price_pct is None or price_pct <= 0.15

    if usage_changed and usage_pct is not None and usage_pct > 0.2 and (price_close or not price_changed):
        et = "usage_overestimated" if nu < ou else "usage_underestimated"
        return _classification(
            et,
            confidence=0.88,
            reason=f"用量 {old_usage} → {new_usage}（变化约 {usage_pct:.0%}）",
            evidence=evidence,
            suggested_rule=_suggest_usage_rule(material_name, new_usage, context, et),
        )

    if price_changed and price_pct is not None and price_pct > 0.15 and (usage_close or not usage_changed):
        return _classification(
            "unit_price_wrong",
            confidence=0.86,
            reason=f"单价 {old_price} → {new_price}（变化约 {price_pct:.0%}）",
            evidence=evidence,
        )

    if new_usage and new_price:
        expected = _first_number(new_usage) and _first_number(new_price)
        if expected is not None:
            expected_amt = round(float(_first_number(new_usage)) * float(_first_number(new_price)), 2)
            if new_amt > 0 and abs(expected_amt - new_amt) > 0.02:
                return _classification(
                    "amount_mismatch",
                    confidence=0.8,
                    reason=f"小计 {new_amt} 与 用量×单价 {expected_amt} 不闭环",
                    evidence={**evidence, "expected_amount": expected_amt},
                )

    if str(context.get("field_name") or "") == "processing_fee":
        return _classification(
            "processing_fee_wrong",
            confidence=0.82,
            reason="加工费被管理员修正",
            evidence=evidence,
        )
    if str(context.get("field_name") or "") in {"gross_margin_rate", "structure_text"}:
        return _classification(
            "margin_or_quote_formula_wrong",
            confidence=0.7,
            reason="报价公式相关字段被修正",
            evidence=evidence,
        )
    if "包装" in material_name:
        return _classification("packaging_wrong", confidence=0.65, reason="包装字段修正", evidence=evidence)

    if usage_changed or price_changed or abs(old_amt - new_amt) > 0.02:
        return _classification("unknown", confidence=0.5, reason="检测到修正但无法精确归因", evidence=evidence)
    return _classification("unknown", confidence=0.3, reason="无实质差异", evidence=evidence)


def _suggest_usage_rule(
    material_name: str,
    corrected_usage: str,
    context: dict[str, Any],
    error_type: str,
) -> dict[str, Any]:
    st = _structure_blob(context)
    pn = str(context.get("product_name") or "")
    pt = str(context.get("product_type") or "")
    payload: dict[str, Any] = {
        "rule_type": "usage_correction",
        "field_name": "usage",
        "corrected_value": corrected_usage,
        "match_keywords": [material_name[:40]] if material_name else [],
        "match_product_keywords": [pt] if pt else [],
        "match_structure_keywords": [],
        "product_type_pattern": pt,
        "product_name_pattern": pn[:60] if pn else "",
        "material_spec_pattern": str(context.get("material_spec") or ""),
        "reason": f"{error_type}：{material_name} 用量修正为 {corrected_usage}",
    }
    if "DCF" in material_name.upper() or "dcf" in material_name.lower():
        payload["match_keywords"] = ["DCF", "dcf外料", "dcf"]
        payload["product_type_pattern"] = pt or "收纳包"
        payload["match_structure_keywords"] = ["立体收纳包", "无肩带", "无提手", "无外袋", "四周包边"]
        payload["size_condition_json"] = {"max_l_cm": 25, "max_w_cm": 20, "max_h_cm": 15, "max_longest_cm": 25}
    elif "收纳" in pn or "收纳" in pt:
        payload["match_structure_keywords"] = ["立体收纳包", "无肩带", "无提手"]
    if st:
        for kw in ("无肩带", "无提手", "无外袋", "四周包边", "立体收纳包"):
            if kw in st and kw not in payload["match_structure_keywords"]:
                payload.setdefault("match_structure_keywords", []).append(kw)
    return payload


def _row_to_candidate_dict(row) -> dict[str, Any]:
    out = {k: row[k] for k in row.keys()}
    for key in ("evidence_json", "suggested_rule_json", "product_size_json"):
        raw = out.get(key)
        if isinstance(raw, str) and raw.strip():
            try:
                out[key.replace("_json", "")] = json.loads(raw)
            except json.JSONDecodeError:
                out[key.replace("_json", "")] = raw
    if str(out.get("status") or "") == CANDIDATE_STATUS_APPLIED:
        out["status"] = CANDIDATE_STATUS_APPROVED
    return out


def insert_correction_candidate(**kwargs: Any) -> str:
    init_correction_learning_storage()
    cid = str(kwargs.get("candidate_id") or uuid.uuid4())
    now = _utc_now_iso()
    conn = _connect()
    try:
        ensure_candidate_tables(conn)
        conn.execute(
            """
            INSERT INTO quote_correction_candidates (
                candidate_id, created_at, updated_at, quote_uid, quote_id, source_file_name,
                product_name, product_type, product_size_text, product_size_json, structure_text,
                material_name, material_role, material_spec, field_name,
                system_usage, system_unit_price, system_amount,
                corrected_usage, corrected_unit_price, corrected_amount,
                system_total_cost, corrected_total_cost, total_cost_gap, total_cost_gap_pct,
                error_type, confidence, reason, evidence_json, suggested_rule_json,
                status, reviewed_by, reviewed_at, review_note, promoted_rule_id
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                cid,
                now,
                now,
                str(kwargs.get("quote_uid") or ""),
                str(kwargs.get("quote_id") or ""),
                str(kwargs.get("source_file_name") or ""),
                str(kwargs.get("product_name") or ""),
                str(kwargs.get("product_type") or ""),
                str(kwargs.get("product_size_text") or ""),
                json.dumps(kwargs.get("product_size") or {}, ensure_ascii=False),
                str(kwargs.get("structure_text") or "")[:2000],
                str(kwargs.get("material_name") or ""),
                str(kwargs.get("material_role") or ""),
                str(kwargs.get("material_spec") or ""),
                str(kwargs.get("field_name") or ""),
                str(kwargs.get("system_usage") or ""),
                str(kwargs.get("system_unit_price") or ""),
                float(kwargs.get("system_amount") or 0),
                str(kwargs.get("corrected_usage") or ""),
                str(kwargs.get("corrected_unit_price") or ""),
                float(kwargs.get("corrected_amount") or 0),
                kwargs.get("system_total_cost"),
                kwargs.get("corrected_total_cost"),
                kwargs.get("total_cost_gap"),
                kwargs.get("total_cost_gap_pct"),
                str(kwargs.get("error_type") or "unknown"),
                float(kwargs.get("confidence") or 0.7),
                str(kwargs.get("reason") or ""),
                json.dumps(kwargs.get("evidence") or {}, ensure_ascii=False),
                json.dumps(kwargs.get("suggested_rule") or {}, ensure_ascii=False),
                str(kwargs.get("status") or CANDIDATE_STATUS_PENDING),
                kwargs.get("reviewed_by"),
                kwargs.get("reviewed_at"),
                kwargs.get("review_note"),
                kwargs.get("promoted_rule_id"),
            ),
        )
        conn.commit()
    finally:
        from quote_correction_learning import _TEST_CONN

        if _TEST_CONN is None:
            conn.close()
    return cid


def list_correction_candidates(
    *,
    status: str = CANDIDATE_STATUS_PENDING,
    error_type: str = "",
    limit: int = 200,
) -> list[dict[str, Any]]:
    init_correction_learning_storage()
    conn = _connect()
    try:
        ensure_candidate_tables(conn)
        sql = "SELECT * FROM quote_correction_candidates WHERE 1=1"
        params: list[Any] = []
        if status:
            if status == CANDIDATE_STATUS_APPROVED:
                sql += " AND status IN (?, ?)"
                params.extend([CANDIDATE_STATUS_APPROVED, CANDIDATE_STATUS_APPLIED])
            else:
                sql += " AND status = ?"
                params.append(status)
        if error_type:
            sql += " AND error_type = ?"
            params.append(error_type)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 500)))
        rows = conn.execute(sql, params).fetchall()
        return [_row_to_candidate_dict(r) for r in rows]
    finally:
        from quote_correction_learning import _TEST_CONN

        if _TEST_CONN is None:
            conn.close()


def get_correction_candidate(candidate_id: str) -> dict[str, Any] | None:
    cid = str(candidate_id or "").strip()
    if not cid:
        return None
    init_correction_learning_storage()
    conn = _connect()
    try:
        ensure_candidate_tables(conn)
        row = conn.execute(
            "SELECT * FROM quote_correction_candidates WHERE candidate_id = ?",
            (cid,),
        ).fetchone()
        return _row_to_candidate_dict(row) if row else None
    finally:
        from quote_correction_learning import _TEST_CONN

        if _TEST_CONN is None:
            conn.close()


def build_rule_from_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    sug = candidate.get("suggested_rule")
    if not isinstance(sug, dict):
        raw = candidate.get("suggested_rule_json")
        if isinstance(raw, str) and raw.strip():
            try:
                sug = json.loads(raw)
            except json.JSONDecodeError:
                sug = {}
        else:
            sug = {}
    material_name = str(candidate.get("material_name") or "")
    corrected_usage = str(candidate.get("corrected_usage") or sug.get("corrected_value") or "")
    corrected_price = str(candidate.get("corrected_unit_price") or "")
    field_name = str(sug.get("field_name") or candidate.get("field_name") or "usage")
    corrected_value = corrected_usage if field_name == "usage" else corrected_price
    if field_name not in TRACK_FIELDS:
        field_name = "usage"
    if not corrected_value:
        corrected_value = corrected_usage or corrected_price
    match_keywords = _json_list(sug.get("match_keywords")) or ([material_name[:40]] if material_name else [])
    match_product = _json_list(sug.get("match_product_keywords"))
    match_structure = _json_list(sug.get("match_structure_keywords"))
    bad_values = [str(candidate.get("system_usage") or "")]
    if not bad_values[0].strip():
        bad_values = []
    rule_id = f"{LEARNED_RULE_ID_PREFIX}{_material_category_key(material_name)}-{field_name}-{_norm_value(bad_values[0] if bad_values else '')}-{_norm_value(corrected_value)}"[:120]
    payload = {
        "product_type_pattern": str(sug.get("product_type_pattern") or candidate.get("product_type") or ""),
        "product_name_pattern": str(sug.get("product_name_pattern") or ""),
        "material_spec_pattern": str(sug.get("material_spec_pattern") or candidate.get("material_spec") or ""),
        "size_condition_json": sug.get("size_condition_json") or {},
        "structure_keywords": match_structure,
        "exclude_keywords": _json_list(sug.get("exclude_keywords")),
        "error_type": candidate.get("error_type"),
        "candidate_id": candidate.get("candidate_id"),
    }
    return {
        "rule_id": rule_id,
        "rule_type": str(sug.get("rule_type") or "usage_correction"),
        "field_name": field_name,
        "match_keywords": match_keywords,
        "match_product_keywords": match_product,
        "match_structure_keywords": match_structure,
        "bad_values": bad_values,
        "corrected_value": corrected_value,
        "confidence": max(APPLY_CONFIDENCE_MIN, float(candidate.get("confidence") or 0.8)),
        "reason": str(candidate.get("reason") or sug.get("reason") or "管理员审批通过的纠错规则"),
        "rule_payload_json": payload,
        "product_type_pattern": payload["product_type_pattern"],
        "product_name_pattern": payload["product_name_pattern"],
        "material_spec_pattern": payload["material_spec_pattern"],
        "size_condition_json": json.dumps(payload["size_condition_json"], ensure_ascii=False),
        "structure_keywords": json.dumps(match_structure, ensure_ascii=False),
        "exclude_keywords": json.dumps(payload["exclude_keywords"], ensure_ascii=False),
    }


def _upsert_rule_from_spec(rule_spec: dict[str, Any], *, approved_by: str) -> str:
    now = _utc_now_iso()
    rid = str(rule_spec["rule_id"])
    conn = _connect()
    try:
        ensure_candidate_tables(conn)
        conn.execute(
            """
            INSERT INTO quote_correction_rules (
                rule_id, rule_type, field_name, match_keywords, match_product_keywords,
                match_structure_keywords, bad_values, corrected_value, confidence, source_count,
                enabled, affects_calculation, created_at, updated_at, reason,
                rule_status, auto_learned, rule_source, approved_by, approved_at,
                product_type_pattern, product_name_pattern, material_spec_pattern,
                size_condition_json, structure_keywords, exclude_keywords, rule_payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, 1, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(rule_id) DO UPDATE SET
                corrected_value = excluded.corrected_value,
                confidence = excluded.confidence,
                enabled = 1,
                rule_status = excluded.rule_status,
                rule_source = excluded.rule_source,
                approved_by = excluded.approved_by,
                approved_at = excluded.approved_at,
                updated_at = excluded.updated_at,
                reason = excluded.reason,
                match_keywords = excluded.match_keywords,
                match_product_keywords = excluded.match_product_keywords,
                match_structure_keywords = excluded.match_structure_keywords,
                bad_values = excluded.bad_values,
                product_type_pattern = excluded.product_type_pattern,
                material_spec_pattern = excluded.material_spec_pattern,
                size_condition_json = excluded.size_condition_json,
                structure_keywords = excluded.structure_keywords,
                rule_payload_json = excluded.rule_payload_json
            """,
            (
                rid,
                rule_spec["rule_type"],
                rule_spec["field_name"],
                json.dumps(rule_spec["match_keywords"], ensure_ascii=False),
                json.dumps(rule_spec["match_product_keywords"], ensure_ascii=False),
                json.dumps(rule_spec["match_structure_keywords"], ensure_ascii=False),
                json.dumps(rule_spec["bad_values"], ensure_ascii=False),
                rule_spec["corrected_value"],
                rule_spec["confidence"],
                now,
                now,
                rule_spec["reason"],
                RULE_STATUS_APPROVED,
                RULE_SOURCE_ADMIN_APPROVED,
                approved_by,
                now,
                rule_spec.get("product_type_pattern", ""),
                rule_spec.get("product_name_pattern", ""),
                rule_spec.get("material_spec_pattern", ""),
                rule_spec.get("size_condition_json", ""),
                rule_spec.get("structure_keywords", "[]"),
                rule_spec.get("exclude_keywords", "[]"),
                json.dumps(rule_spec.get("rule_payload_json") or {}, ensure_ascii=False),
            ),
        )
        conn.commit()
    finally:
        from quote_correction_learning import _TEST_CONN

        if _TEST_CONN is None:
            conn.close()
    return rid


def approve_correction_candidate(
    candidate_id: str,
    *,
    reviewed_by: str = "admin",
    review_note: str = "",
) -> dict[str, Any]:
    cand = get_correction_candidate(candidate_id)
    if not cand:
        raise ValueError("候选不存在。")
    if str(cand.get("status") or "") == CANDIDATE_STATUS_REJECTED:
        raise ValueError("已驳回的候选不能批准。")
    operator = str(reviewed_by or "admin").strip() or "admin"
    note = str(review_note or "").strip()
    rule_spec = build_rule_from_candidate(cand)
    rule_id = _upsert_rule_from_spec(rule_spec, approved_by=operator)
    now = _utc_now_iso()
    conn = _connect()
    try:
        conn.execute(
            """
            UPDATE quote_correction_candidates
            SET status = ?, reviewed_by = ?, reviewed_at = ?, review_note = ?,
                promoted_rule_id = ?, updated_at = ?
            WHERE candidate_id = ?
            """,
            (CANDIDATE_STATUS_APPROVED, operator, now, note, rule_id, now, candidate_id),
        )
        conn.commit()
    finally:
        from quote_correction_learning import _TEST_CONN

        if _TEST_CONN is None:
            conn.close()
    return {"ok": True, "candidate_id": candidate_id, "rule_id": rule_id, "status": CANDIDATE_STATUS_APPROVED}


def reject_correction_candidate(
    candidate_id: str,
    *,
    reviewed_by: str = "admin",
    review_note: str = "",
) -> dict[str, Any]:
    cand = get_correction_candidate(candidate_id)
    if not cand:
        raise ValueError("候选不存在。")
    operator = str(reviewed_by or "admin").strip() or "admin"
    note = str(review_note or "").strip()
    now = _utc_now_iso()
    conn = _connect()
    try:
        conn.execute(
            """
            UPDATE quote_correction_candidates
            SET status = ?, reviewed_by = ?, reviewed_at = ?, review_note = ?, updated_at = ?
            WHERE candidate_id = ?
            """,
            (CANDIDATE_STATUS_REJECTED, operator, now, note, now, candidate_id),
        )
        conn.commit()
    finally:
        from quote_correction_learning import _TEST_CONN

        if _TEST_CONN is None:
            conn.close()
    return {"ok": True, "candidate_id": candidate_id, "status": CANDIDATE_STATUS_REJECTED}


def list_correction_rules(
    *,
    status: str = "",
    enabled: bool | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    init_correction_learning_storage()
    conn = _connect()
    try:
        ensure_candidate_tables(conn)
        sql = "SELECT * FROM quote_correction_rules WHERE 1=1"
        params: list[Any] = []
        if status:
            sql += " AND rule_status = ?"
            params.append(status)
        if enabled is not None:
            sql += " AND enabled = ?"
            params.append(1 if enabled else 0)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 500)))
        rows = conn.execute(sql, params).fetchall()
        return [{k: row[k] for k in row.keys()} for row in rows]
    finally:
        from quote_correction_learning import _TEST_CONN

        if _TEST_CONN is None:
            conn.close()


def toggle_correction_rule(rule_id: str, enabled: bool, *, operator: str = "admin") -> dict[str, Any]:
    rid = str(rule_id or "").strip()
    if not rid:
        raise ValueError("rule_id 不能为空。")
    now = _utc_now_iso()
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT rule_id FROM quote_correction_rules WHERE rule_id = ?",
            (rid,),
        ).fetchone()
        if not row:
            raise ValueError("规则不存在。")
        conn.execute(
            "UPDATE quote_correction_rules SET enabled = ?, updated_at = ? WHERE rule_id = ?",
            (1 if enabled else 0, now, rid),
        )
        conn.commit()
    finally:
        from quote_correction_learning import _TEST_CONN

        if _TEST_CONN is None:
            conn.close()
    return {"ok": True, "rule_id": rid, "enabled": bool(enabled), "operator": operator}


def _default_total_cost(quote: dict[str, Any] | None) -> float | None:
    if not isinstance(quote, dict):
        return None
    tiers = quote.get("tiers")
    if isinstance(tiers, list) and tiers:
        try:
            return round(float(tiers[0].get("total_cost") or tiers[0].get("cost_before_margin") or 0), 2)
        except (TypeError, ValueError):
            pass
    try:
        return round(float(quote.get("system_cost") or 0), 2)
    except (TypeError, ValueError):
        return None


def capture_correction_candidates_from_bom_save(
    quote_uid: str,
    *,
    old_items: list[dict[str, Any]],
    new_items: list[dict[str, Any]],
    quote: dict[str, Any] | None = None,
    old_quote: dict[str, Any] | None = None,
    new_quote: dict[str, Any] | None = None,
    corrected_by: str = "admin",
) -> list[str]:
    """每次 BOM 修正保存后写入 pending 候选（失败不影响主流程）。"""
    if corrected_by != "admin":
        return []
    q = quote if isinstance(quote, dict) else {}
    oq = old_quote if isinstance(old_quote, dict) else {}
    nq = new_quote if isinstance(new_quote, dict) else oq
    ctx_base = {
        "quote_uid": quote_uid,
        "quote_id": str(q.get("quote_id") or ""),
        "product_name": str(q.get("product_name") or ""),
        "product_type": str(q.get("product_type") or q.get("sheet_metadata", {}).get("产品类型") or ""),
        "structure_text": _structure_blob(q),
        "product_size": q.get("product_size") if isinstance(q.get("product_size"), dict) else {},
        "product_size_text": str(q.get("product_size_text") or ""),
        "source_file_name": str(q.get("source_file_name") or q.get("file_name") or ""),
    }
    old_map = {
        str(r.get("name") or "").strip(): r
        for r in (old_items or [])
        if isinstance(r, dict) and str(r.get("name") or "").strip()
    }
    new_map = {
        str(r.get("name") or "").strip(): r
        for r in (new_items or [])
        if isinstance(r, dict) and str(r.get("name") or "").strip()
    }
    created: list[str] = []
    names = set(old_map) | set(new_map)
    for name in sorted(names):
        old_row = old_map.get(name) or {}
        new_row = new_map.get(name) or {}
        if not old_row and not new_row:
            continue
        ctx = {
            **ctx_base,
            "material_spec": str(new_row.get("spec") or old_row.get("spec") or ""),
            "material_role": str(new_row.get("role") or old_row.get("role") or ""),
        }
        classified = classify_correction_error(old_row, new_row, ctx)
        if classified.get("error_type") == "unknown" and not classified.get("reason", "").startswith("检测到修正"):
            continue
        try:
            cid = insert_correction_candidate(
                quote_uid=quote_uid,
                quote_id=ctx_base["quote_id"],
                source_file_name=ctx_base["source_file_name"],
                product_name=ctx_base["product_name"],
                product_type=ctx_base["product_type"],
                product_size_text=ctx_base["product_size_text"],
                product_size=ctx_base["product_size"],
                structure_text=ctx_base["structure_text"],
                material_name=name,
                material_role=ctx["material_role"],
                material_spec=ctx["material_spec"],
                field_name="usage" if str(old_row.get("usage") or "") != str(new_row.get("usage") or "") else "unit_price",
                system_usage=str(old_row.get("usage") or ""),
                system_unit_price=str(old_row.get("unit_price") or ""),
                system_amount=_parse_amount(old_row),
                corrected_usage=str(new_row.get("usage") or ""),
                corrected_unit_price=str(new_row.get("unit_price") or ""),
                corrected_amount=_parse_amount(new_row),
                error_type=classified.get("error_type"),
                confidence=classified.get("confidence"),
                reason=classified.get("reason"),
                evidence=classified.get("evidence"),
                suggested_rule=classified.get("suggested_rule"),
                status=CANDIDATE_STATUS_PENDING,
            )
            created.append(cid)
        except Exception:
            logger.debug("insert_correction_candidate failed name=%s", name, exc_info=True)

    sys_cost = _default_total_cost(oq)
    new_cost = _default_total_cost(nq)
    if sys_cost is not None and new_cost is not None:
        gap = round(new_cost - sys_cost, 2)
        pct = round(gap / sys_cost * 100, 2) if sys_cost else None
        if abs(gap) > max(12.0, abs(sys_cost) * 0.07):
            classified = _classification(
                "margin_or_quote_formula_wrong",
                confidence=0.78,
                reason=f"总成本 {sys_cost} → {new_cost}（差 {gap}）",
                evidence={"system_total_cost": sys_cost, "corrected_total_cost": new_cost},
            )
            try:
                cid = insert_correction_candidate(
                    quote_uid=quote_uid,
                    quote_id=ctx_base["quote_id"],
                    source_file_name=ctx_base["source_file_name"],
                    product_name=ctx_base["product_name"],
                    product_type=ctx_base["product_type"],
                    product_size=ctx_base["product_size"],
                    structure_text=ctx_base["structure_text"],
                    material_name="[总成本]",
                    field_name="total_cost",
                    system_total_cost=sys_cost,
                    corrected_total_cost=new_cost,
                    total_cost_gap=gap,
                    total_cost_gap_pct=pct,
                    error_type=classified["error_type"],
                    confidence=classified["confidence"],
                    reason=classified["reason"],
                    evidence=classified["evidence"],
                    status=CANDIDATE_STATUS_PENDING,
                )
                created.append(cid)
            except Exception:
                logger.debug("total cost candidate insert failed", exc_info=True)
    return created


def parse_size_condition(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            obj = json.loads(raw)
            return obj if isinstance(obj, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def size_matches_condition(product_size: dict[str, Any] | None, condition: dict[str, Any] | None) -> bool:
    if not condition:
        return True
    ps = product_size if isinstance(product_size, dict) else {}
    def _dim(*keys: str) -> float:
        for k in keys:
            try:
                v = float(ps.get(k) or 0)
            except (TypeError, ValueError):
                v = 0.0
            if v > 0:
                return v
        return 0.0

    l_cm = _dim("LCM", "l", "length", "长")
    w_cm = _dim("WCM", "w", "width", "宽")
    h_cm = _dim("HCM", "h", "height", "高")
    longest = max(l_cm, w_cm, h_cm) if any((l_cm, w_cm, h_cm)) else 0.0
    checks = (
        ("max_l_cm", l_cm),
        ("max_w_cm", w_cm),
        ("max_h_cm", h_cm),
        ("max_longest_cm", longest),
    )
    for key, val in checks:
        try:
            limit = float(condition.get(key))
        except (TypeError, ValueError):
            continue
        if val > 0 and val > limit + 1e-6:
            return False
    return True


def rule_row_extended_match(row: Any, ctx: dict[str, Any]) -> bool:
    """扩展规则匹配：product/material/spec/size/structure/exclude。"""
    data = dict(row) if hasattr(row, "keys") else {}
    payload = parse_size_condition(data.get("rule_payload_json"))
    if not payload and data.get("size_condition_json"):
        payload = parse_size_condition(data.get("size_condition_json"))

    st = _structure_blob(ctx)
    pn = str(ctx.get("product_name") or "")
    pt = str(ctx.get("product_type") or "")
    spec = str(ctx.get("material_spec") or ctx.get("spec") or "")

    ptp = str(data.get("product_type_pattern") or payload.get("product_type_pattern") or "")
    if ptp and ptp not in pt and ptp not in pn:
        return False
    pnp = str(data.get("product_name_pattern") or payload.get("product_name_pattern") or "")
    if pnp and pnp not in pn:
        return False
    msp = str(data.get("material_spec_pattern") or payload.get("material_spec_pattern") or "")
    if msp and msp.lower() not in spec.lower() and msp.lower() not in str(ctx.get("material_name") or "").lower():
        return False

    structure_kws = _json_list(data.get("structure_keywords")) or _json_list(payload.get("structure_keywords"))
    if not structure_kws:
        structure_kws = _json_list(data.get("match_structure_keywords"))
    if structure_kws and not _matches_keywords(st, structure_kws):
        return False

    exclude_kws = _json_list(data.get("exclude_keywords")) or _json_list(payload.get("exclude_keywords"))
    blob = f"{pn} {pt} {st} {spec}".lower()
    if exclude_kws and any(k.lower() in blob for k in exclude_kws):
        return False

    size_cond = parse_size_condition(data.get("size_condition_json")) or parse_size_condition(payload.get("size_condition_json"))
    ps = ctx.get("product_size") if isinstance(ctx.get("product_size"), dict) else {}
    if not size_matches_condition(ps, size_cond):
        return False
    return True
