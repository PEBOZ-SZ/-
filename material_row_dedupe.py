"""需求表 BOM 行预处理：避免「网布+EVA+底 X-PAC」复合行与单独 X-PAC 等行重复计整码。"""
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any


def _norm(s: str) -> str:
    t = (s or "").strip().lower()
    t = re.sub(r"\s+", "", t)
    return t


def _is_composite_material_name(name: str) -> bool:
    """Composite sandwich / multi-ply description (一格多料)."""
    n = (name or "").strip()
    if len(n) < 8:
        return False
    if "+" in n or "＋" in n:
        return True
    nl = n.lower()
    if any(k in n for k in ("三明治", "复合料", "贴合", "双层面料")) and len(n) >= 10:
        return True
    if ("网布" in n or "eva" in nl) and ("x-pac" in nl or "xpac" in nl):
        return True
    if "整块" in n and ("eva" in nl or "网" in n) and ("x-pac" in nl or "xpac" in nl):
        return True
    return False


def _mentions_xpac(text: str) -> bool:
    t = _norm(text)
    return bool(re.search(r"x[\s-]*pac|vx\s*\d+|vx21", t))


def _mentions_dch_or_dcf(text: str) -> bool:
    t = _norm(text)
    return "dch" in t or "dcf" in t or "3.2oz" in t or "1.43oz" in t


def _composite_texts_cover_xpac(composite_names: list[str]) -> bool:
    for c in composite_names:
        cl = c.lower()
        if "x-pac" in cl or "xpac" in cl or "vx" in cl:
            return True
    return False


_WIDTH_DIM_TOKEN = re.compile(
    r"(幅宽|门幅|宽幅)\s*[：:]?\s*(\d+)\s*(?:CM|厘米|毫米|MM|英寸|inch|m)?",
    re.I,
)


def _row_amount_value(row: dict[str, Any]) -> float:
    raw = row.get("amount")
    if raw is None or raw == "":
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        return 0.0


def _width_dimension_bucket_key(name: str) -> str:
    nm = str(name or "").strip()
    m = _WIDTH_DIM_TOKEN.search(nm)
    if not m:
        return ""
    return f"w:{int(m.group(2))}"


def merge_duplicate_width_label_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """合并「幅宽145CM」「宽幅145cm」等数值相同的门幅描述重复行。"""
    if not items or len(items) < 2:
        return items
    buckets: dict[str, list[int]] = {}
    for idx, row in enumerate(items):
        if not isinstance(row, dict):
            continue
        bk = _width_dimension_bucket_key(str(row.get("name") or ""))
        if not bk:
            continue
        buckets.setdefault(bk, []).append(idx)
    skip_idx: set[int] = set()
    replace_idx: dict[int, dict[str, Any]] = {}
    for _bk, ixlist in buckets.items():
        if len(ixlist) < 2:
            continue
        lead_idx = max(ixlist, key=lambda i: len(str(items[i].get("name") or "")))
        total_amt = round(sum(_row_amount_value(items[i]) for i in ixlist), 2)
        keeper = dict(items[lead_idx])
        merged_names = sorted(
            {str(items[i].get("name") or "").strip() for i in ixlist if str(items[i].get("name") or "").strip()}
        )
        if len(merged_names) > 1:
            keeper["name"] = merged_names[0]
            note = "; ".join(merged_names)
            prev = str(keeper.get("spec") or "").strip()
            tail = f"合并门幅同源:{note}"
            keeper["spec"] = f"{prev}；{tail}" if prev and prev != "-" else tail
        keeper["amount"] = total_amt
        keeper["amount_text"] = f"{total_amt:.2f}元"
        replace_idx[lead_idx] = keeper
        for i in ixlist:
            if i != lead_idx:
                skip_idx.add(i)
    out: list[dict[str, Any]] = []
    for i, row in enumerate(items):
        if i in skip_idx:
            continue
        out.append(replace_idx.get(i, row))
    return out if out else items

def collapse_fabric_reverse_use_shadow_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """去掉「同款面料仅为反用说明」的假 BOM 行——避免与主料行双倍计价。

    典型：主料格已有 3.2oz DCH，结构说明里「××部位 DCH 面料反用（450元/码）」；
    Agent 再加一行并按 450×1 码计价 → 应与主料合并为规格备注，不参与二次计费。
    """
    if len(items) < 2:
        return items

    def is_shadow(nm: str) -> bool:
        n = str(nm or "").strip()
        if len(n) < 10:
            return False
        if "反用" in n:
            return True
        if re.search(r"反面\s*做面|翻面|面料\s*反", n):
            return True
        if "悬用" in n and ("面料" in n or _mentions_dch_or_dcf(n)):
            return True
        return False

    normals: list[dict[str, Any]] = []
    shadows: list[dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if is_shadow(name):
            shadows.append(dict(raw))
        else:
            normals.append(dict(raw))

    out: list[dict[str, Any]] = list(normals)
    if not shadows:
        return out if out else items

    def find_anchor(nm: str) -> int | None:
        idx: int | None = None
        if _mentions_dch_or_dcf(nm):
            idx = next(
                (
                    i
                    for i, peer in enumerate(out)
                    if _mentions_dch_or_dcf(str(peer.get("name") or ""))
                    and len(str(peer.get("name") or "")) <= 42
                    and not is_shadow(str(peer.get("name") or ""))
                ),
                None,
            )
        if idx is None and _mentions_xpac(nm):
            idx = next(
                (
                    i
                    for i, peer in enumerate(out)
                    if _mentions_xpac(str(peer.get("name") or ""))
                    and len(str(peer.get("name") or "")) <= 52
                    and not is_shadow(str(peer.get("name") or ""))
                ),
                None,
            )
        return idx

    for shadow in shadows:
        name = str(shadow.get("name") or "").strip()
        anchor_idx = find_anchor(name)
        if anchor_idx is None:
            out.append(dict(shadow))
            continue
        keeper = dict(out[anchor_idx])
        prev_spec = str(keeper.get("spec") or "").strip()
        suffix = name if len(name) <= 140 else name[:137] + "…"
        tag = f"并入工艺备注（非独立用料）：{suffix}"
        keeper["spec"] = f"{prev_spec}；{tag}" if prev_spec and prev_spec != "-" else tag
        out[anchor_idx] = keeper
    return out if out else items


def dedupe_composite_overlapping_fabric_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    存在复合夹层行时，删除已被复合行语义覆盖的「短名单独面料行」，
    减少后续模型对每行都给 1 码造成的翻倍。

    典型：单独一行「X-PAC VX21」+ 一行「网布+EVA+底 x-pac」→ 删前者。
    「3.2oz DCH」若复合行不含 DCH，必须保留（常见前幅 DCH、后幅夹层）。
    """
    if not items or len(items) < 2:
        return items
    names = [str(it.get("name") or "").strip() for it in items]
    comp_idx = [i for i, n in enumerate(names) if _is_composite_material_name(n)]
    if not comp_idx:
        return items
    composites = [names[i] for i in comp_idx]

    out: list[dict[str, Any]] = []
    for i, it in enumerate(items):
        n = names[i]
        if i in comp_idx:
            out.append(it)
            continue
        if len(n) > 55:
            out.append(it)
            continue

        # 单独短行的 X-PAC，复合层已描述底布/夹层 X-PAC → 去掉重复
        if (
            _mentions_xpac(n)
            and len(n) <= 40
            and _composite_texts_cover_xpac(composites)
        ):
            continue

        # 仅当复合行文字里也出现 DCH/DCF 时，才删短行的重复 DCH（避免误删前幅单独 DCH）
        if _mentions_dch_or_dcf(n) and len(n) <= 40:
            if any(_mentions_dch_or_dcf(c) for c in composites):
                continue

        out.append(it)

    return out if out else items


_STRUCTURE_MERGED_IN_PLACE_PATTERN = re.compile(r"已并入第\s*\d+\s*行")


def _fabric_dedupe_bucket(name: str) -> str:
    """同一桶内的行若为「简短 BOM + 结构说明长句」并存，只保留 BOM 行。"""
    raw = str(name or "").strip()
    if not raw:
        return ""
    nl = raw.lower()
    nu = _norm(raw)
    if _mentions_xpac(raw):
        return "fab:xpac_vx"
    if _mentions_dch_or_dcf(raw):
        return "fab:dyneema"
    if "ultra" in nu:
        return "fab:ultra"
    # 防水拉链族（避免「5#YKK防水拉链」与「采用防水拉链…」两条并存）
    if "拉链" in raw and ("防水" in raw or "ykk" in nl or re.search(r"\d\s*#", raw)):
        return "acc:zip_water"
    return ""


def _looks_like_structure_narrative_row_name(name: str) -> bool:
    """结构说明拆出来的长描述行（非简短主料/辅料标题）。"""
    n = str(name or "").strip()
    if len(n) < 14:
        return False
    prose = ("主体", "采用", "背板", "肩带", "进口", "面料", "包身")
    hits = sum(1 for m in prose if m in n)
    if hits >= 2:
        return True
    if len(n) >= 18 and hits >= 1:
        return True
    # 「采用……拉链」「主体……拉链」类
    if len(n) >= 12 and "拉链" in n and ("采用" in n or "主体" in n):
        return True
    return False


def drop_duplicate_structure_narrative_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """去掉与 BOM 同行的「结构说明复述」物料行（同面料桶只保留简短计价行）。

    仅在「桶内已有非叙述型 keeper 且 keeper 已有小计」或「叙述行本身未计价」时删除叙述行，
    避免误删唯一有价数据。"""
    if not items or len(items) < 2:
        return items

    buckets: dict[str, list[int]] = {}
    for i, raw in enumerate(items):
        if not isinstance(raw, dict):
            continue
        bk = _fabric_dedupe_bucket(str(raw.get("name") or ""))
        if bk:
            buckets.setdefault(bk, []).append(i)

    drop_ix: set[int] = set()
    for ixlist in buckets.values():
        if len(ixlist) < 2:
            continue
        keeper_candidates = [
            i
            for i in ixlist
            if not _looks_like_structure_narrative_row_name(str(items[i].get("name") or ""))
        ]
        if not keeper_candidates:
            continue
        keeper_idx = min(keeper_candidates)
        keeper_amt = _row_amount_value(items[keeper_idx])

        for i in ixlist:
            if i == keeper_idx:
                continue
            if not _looks_like_structure_narrative_row_name(str(items[i].get("name") or "")):
                continue
            nar_amt = _row_amount_value(items[i])
            if keeper_amt > 1e-6 or nar_amt <= 1e-6:
                drop_ix.add(i)

    out = [row for j, row in enumerate(items) if j not in drop_ix]
    return out if out else items


def drop_structure_duplicate_markup_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """去掉「已并入第 N 行」类结构说明重复行——与同主料合并计价后不应再出现在明细表里。"""
    if not items:
        return items
    kept: list[dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        blob = "\n".join(
            str(raw.get(k) or "")
            for k in ("calc_note", "calc_method", "spec", "note", "name")
        )
        if _STRUCTURE_MERGED_IN_PLACE_PATTERN.search(blob):
            continue
        kept.append(raw)
    return kept if kept else items


def _calc_blob_for_row(row: dict[str, Any]) -> str:
    return "\n".join(str(row.get(k) or "") for k in ("calc_note", "calc_method", "spec", "note", "name"))


def _should_hide_zero_merge_placeholder(row: dict[str, Any]) -> bool:
    """小计为 0 且文案写明「已合并到其它行 / 禁止双计」的占位行，不在明细里展示。"""
    if _row_amount_value(row) > 1e-6:
        return False
    blob = _calc_blob_for_row(row)
    if not blob.strip():
        return False
    if "已合并计入" in blob:
        return True
    if re.search(r"与首行.{0,80}重复", blob):
        return True
    if "禁止双计" in blob and ("重复" in blob or "合并" in blob):
        return True
    return False


def drop_zero_subtotal_merge_placeholder_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """去掉「重复已合并」说明且小计为 0 的行（例如主面料 DCF 占位解释行）。"""
    if not items:
        return items
    kept: list[dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        if _should_hide_zero_merge_placeholder(raw):
            continue
        kept.append(raw)
    return kept if kept else items


_USAGE_VALUE_UNIT_RE = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)\s*([^\d\s]+)\s*$")
_PRICE_NUMBER_RE = re.compile(r"([+-]?\d+(?:\.\d+)?)")


def _quote_merge_norm_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    return re.sub(r"\s+", "", text)


def _quote_merge_area(row: dict[str, Any]) -> str:
    return _quote_merge_norm_text(row.get("section_key") or row.get("area") or "")


def _quote_merge_calc_core(row: dict[str, Any]) -> str:
    raw = row.get("calc_note")
    if raw is None or str(raw).strip() == "":
        raw = row.get("calc_method")
    text = _quote_merge_norm_text(raw)
    aliases = (
        ("裁片面积", "piece_area"),
        ("面积表", "piece_area"),
        ("面积合计", "piece_area"),
        ("主料按裁片", "piece_area"),
        ("拉链", "zipper"),
        ("按长度", "length"),
        ("长度", "length"),
        ("按个数", "count"),
        ("个数", "count"),
        ("按数量", "count"),
    )
    for marker, core in aliases:
        if _quote_merge_norm_text(marker) in text:
            return core
    return text


def _quote_merge_key(row: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        _quote_merge_norm_text(row.get("name")),
        _quote_merge_norm_text(row.get("spec")),
        _quote_merge_norm_text(row.get("unit_price")),
        _quote_merge_area(row),
        _quote_merge_calc_core(row),
    )


def _quote_same_name_signature(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        _quote_merge_norm_text(row.get("spec")),
        _quote_merge_norm_text(row.get("unit_price")),
        _quote_merge_area(row),
        _quote_merge_calc_core(row),
    )


def _parse_decimal_text(value: Any) -> Decimal | None:
    text = unicodedata.normalize("NFKC", str(value or "")).replace(",", "").strip()
    if not text:
        return None
    m = _PRICE_NUMBER_RE.search(text)
    if not m:
        return None
    try:
        return Decimal(m.group(1))
    except InvalidOperation:
        return None


def _parse_usage_value_unit(value: Any) -> tuple[Decimal, str] | None:
    text = unicodedata.normalize("NFKC", str(value or "")).replace(",", "").strip()
    m = _USAGE_VALUE_UNIT_RE.match(text)
    if not m:
        return None
    try:
        amount = Decimal(m.group(1))
    except InvalidOperation:
        return None
    unit = m.group(2).strip()
    if not unit:
        return None
    return amount, unit


def _format_decimal(value: Decimal, places: int = 6) -> str:
    quant = Decimal("1").scaleb(-places)
    normalized = value.quantize(quant).normalize()
    if normalized == normalized.to_integral():
        return str(normalized.to_integral())
    return format(normalized, "f")


def _sum_usage_texts(usages: list[str]) -> str | None:
    parsed = [_parse_usage_value_unit(u) for u in usages]
    if not parsed or any(p is None for p in parsed):
        return None
    units = {_quote_merge_norm_text(p[1]) for p in parsed if p is not None}
    if len(units) != 1:
        return None
    first_unit = parsed[0][1] if parsed[0] is not None else ""
    total = sum((p[0] for p in parsed if p is not None), Decimal("0"))
    return f"{_format_decimal(total)}{first_unit}"


def _sum_amounts(rows: list[dict[str, Any]]) -> float | None:
    values: list[Decimal] = []
    for row in rows:
        raw = row.get("amount")
        if raw is None or str(raw).strip() == "":
            return None
        parsed = _parse_decimal_text(raw)
        if parsed is None:
            return None
        values.append(parsed)
    if not values:
        return None
    return float(sum(values, Decimal("0")).quantize(Decimal("0.01")))


def _amount_from_usage_and_price(usage: Any, unit_price: Any) -> float | None:
    usage_parsed = _parse_usage_value_unit(usage)
    price = _parse_decimal_text(unit_price)
    if usage_parsed is None or price is None:
        return None
    return float((usage_parsed[0] * price).quantize(Decimal("0.01")))


def _append_unique_text(existing: Any, additions: list[str]) -> str:
    parts: list[str] = []
    for raw in [str(existing or "")] + additions:
        for piece in re.split(r"[;；]\s*", raw):
            text = piece.strip()
            if text and text not in parts:
                parts.append(text)
    return "；".join(parts)


def _mark_same_name_manual_confirmation(items: list[dict[str, Any]]) -> None:
    by_name: dict[str, list[dict[str, Any]]] = {}
    for row in items:
        name_key = _quote_merge_norm_text(row.get("name"))
        if name_key:
            by_name.setdefault(name_key, []).append(row)
    for rows in by_name.values():
        signatures = {_quote_same_name_signature(row) for row in rows}
        if len(rows) < 2 or len(signatures) < 2:
            continue
        for row in rows:
            row["needs_manual_confirm"] = True
            row["recognition_status"] = row.get("recognition_status") or "same_name_review"
            msg = "同名不同规格/单价/区域/计算方式，需人工确认"
            row["recognition_reason"] = _append_unique_text(row.get("recognition_reason"), [msg])


def merge_duplicate_quote_material_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Safely merge quote material rows with identical name/spec/price/area/calc method.

    Rows sharing only the same name are not merged when spec, price, area, or calc
    method differ; they are marked for human confirmation instead.
    """
    if not isinstance(items, list) or len(items) < 2:
        return items

    buckets: dict[tuple[str, str, str, str, str], list[tuple[int, dict[str, Any]]]] = {}
    passthrough: list[tuple[int, dict[str, Any]]] = []
    for idx, raw in enumerate(items):
        if not isinstance(raw, dict):
            continue
        row = dict(raw)
        key = _quote_merge_key(row)
        if not key[0]:
            passthrough.append((idx, row))
            continue
        buckets.setdefault(key, []).append((idx, row))

    merged_by_first_index: dict[int, dict[str, Any]] = {}
    dropped_indices: set[int] = set()
    for grouped in buckets.values():
        if len(grouped) < 2:
            idx, row = grouped[0]
            merged_by_first_index[idx] = row
            continue
        indices = [idx for idx, _row in grouped]
        rows = [row for _idx, row in grouped]
        keeper = dict(rows[0])
        usages = [str(row.get("usage") or "").strip() for row in rows]
        summed_usage = _sum_usage_texts(usages)
        if summed_usage is not None:
            keeper["usage"] = summed_usage
            if keeper.get("total_usage") is not None:
                keeper["total_usage"] = summed_usage
        else:
            keeper["usage"] = usages[0] if usages else str(keeper.get("usage") or "")
            note = f"由 {len(rows)} 条同名行合并，原用量分别为 " + "、".join(u or "-" for u in usages)
            keeper["remark"] = _append_unique_text(keeper.get("remark"), [note])

        summed_amount = _sum_amounts(rows)
        if summed_amount is None:
            summed_amount = _amount_from_usage_and_price(keeper.get("usage"), keeper.get("unit_price"))
        if summed_amount is not None:
            keeper["amount"] = summed_amount
            keeper["amount_text"] = f"{summed_amount:.2f}元"

        notes = [
            str(row.get("calc_note") or row.get("calc_method") or "").strip()
            for row in rows
            if str(row.get("calc_note") or row.get("calc_method") or "").strip()
        ]
        remarks = [str(row.get("remark") or "").strip() for row in rows if str(row.get("remark") or "").strip()]
        if notes:
            keeper["calc_note"] = _append_unique_text("", notes)
            keeper["calc_method"] = keeper["calc_note"]
        if remarks and summed_usage is not None:
            keeper["remark"] = _append_unique_text(keeper.get("remark"), remarks)
        keeper["merged_duplicate_count"] = len(rows)
        keeper["merge_hint"] = f"已合并 {len(rows)} 条重复材料行"
        keeper["source_row_indices"] = indices
        keeper["merged_from_rows"] = [dict(row) for row in rows]
        merged_by_first_index[indices[0]] = keeper
        dropped_indices.update(indices[1:])

    for idx, row in passthrough:
        merged_by_first_index[idx] = row

    out: list[dict[str, Any]] = []
    for idx in range(len(items)):
        if idx in dropped_indices:
            continue
        row = merged_by_first_index.get(idx)
        if row is not None:
            out.append(row)
    _mark_same_name_manual_confirmation(out)
    return out if out else items
