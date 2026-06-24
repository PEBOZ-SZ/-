"""按材料汇总裁片面积：先汇总、后明细（只读展示，不参与计价）。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from material_spec_usage_enricher import _is_fabric_material

_CALC_SIZE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*[×xX*]\s*(\d+(?:\.\d+)?)\s*[×xX*]\s*(\d+(?:\.\d+)?)",
    re.I,
)
_DIM_PAIR_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*[×xX*]\s*(\d+(?:\.\d+)?)\s*(?:cm|CM|厘米)?",
    re.I,
)
_LWH_TRIPLE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*[×xX*]\s*(\d+(?:\.\d+)?)\s*[×xX*]\s*(\d+(?:\.\d+)?)",
    re.I,
)

_H_LEN_RE = re.compile(r"(?:包身)?(?:横向长度|长度)\s*[：:]?\s*(\d+(?:\.\d+)?)", re.I)
_H_HEIGHT_RE = re.compile(r"高度\s*[：:]?\s*(\d+(?:\.\d+)?)", re.I)
_H_WIDTH_RE = re.compile(
    r"(?:底部宽度\s*[\/／]\s*侧宽|底部宽度\s*[\/／]?\s*侧宽|底部宽度|侧宽)\s*[：:]?\s*(\d+(?:\.\d+)?)",
    re.I,
)

_BACK_POCKET_RE = re.compile(r"后幅[^，,。；;\n]{0,12}(?:大面积)?外贴袋", re.I)

_BADGE_COUNT_RE = re.compile(
    r"PU拉牌|PU牌|PU标|皮牌|皮标|Logo牌|LOGO牌|橡胶牌|标牌|吊牌|拉牌",
    re.I,
)
_PU_PIECE_AREA_RE = re.compile(
    r"底部PU片|^PU片$|PU面料|底部隔离|隔离片|隔离面料",
    re.I,
)

FORMULA_TEXT: dict[str, str] = {
    "panel": "长×高×片数",
    "bottom": "长×宽×片数",
    "side": "宽×高×片数",
    "perimeter": "2×(长+宽)×高",
    "perimeter_with_bottom": "2×(长+宽)×高 + 长×宽",
    "pair_size": "长×宽×片数",
    "pending": "待补充",
}

MEASURE_KIND_LABELS: dict[str, str] = {
    "main_fabric_area": "主料展开面积",
    "lining_area": "里布展开面积",
    "padding_area": "内部托料面积",
    "pu_piece_area": "PU片面积",
    "mesh_area": "网布面积",
    "length": "按长度计量",
    "count_with_length": "按条计量",
    "count": "按数量计量",
    "process": "工艺项",
    "pending": "待复核",
}


@dataclass
class ParsedMaterialRemark:
    body_length: float | None = None
    body_height: float | None = None
    body_width: float | None = None
    front_pocket_height: float | None = None
    side_pocket_height: float | None = None
    trolley_sleeve_width: float | None = None
    trolley_sleeve_height: float | None = None
    bottom_pu_length: float | None = None
    bottom_pu_width: float | None = None
    mentions: set[str] = field(default_factory=set)


def _fmt_dim(n: float) -> str:
    if abs(n - round(n)) < 1e-6:
        return str(int(round(n)))
    return f"{n:g}"


def _fmt_lwh(l: float, h: float, w: float) -> str:
    return f"{_fmt_dim(l)}×{_fmt_dim(h)}×{_fmt_dim(w)}"


def _first_float(patterns: list[str], blob: str) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, blob, re.I)
        if match:
            return float(match.group(1))
    return None


def _remark_mentions(blob: str, keywords: str) -> bool:
    return bool(re.search(keywords, blob, re.I))


def _parse_material_remark(remark: str) -> ParsedMaterialRemark:
    blob = str(remark or "").strip()
    parsed = ParsedMaterialRemark()
    if not blob or blob in {"无", "-", "—"}:
        return parsed

    parsed.body_length = _first_float(
        [
            r"包身横向长度\s*[：:，,]?\s*(\d+(?:\.\d+)?)",
            r"(?:包身)?横向长度\s*[：:，,]?\s*(\d+(?:\.\d+)?)",
            r"长\s*[：:，,]?\s*(\d+(?:\.\d+)?)\s*(?:cm|CM|厘米)?",
        ],
        blob,
    )
    parsed.body_height = _first_float(
        [
            r"包身横向长度[^，,；;\n]{0,40}高度\s*[：:，,]?\s*(\d+(?:\.\d+)?)",
            r"(?:^|[，,；;\n]\s*)高度\s*[：:，,]?\s*(\d+(?:\.\d+)?)",
            r"高(?:度)?\s*[：:，,]?\s*(\d+(?:\.\d+)?)\s*(?:cm|CM|厘米)?",
        ],
        blob,
    )
    parsed.body_width = _first_float(
        [
            r"底部宽度\s*[\/／]\s*侧宽\s*[：:，,]?\s*(\d+(?:\.\d+)?)",
            r"底部宽度\s*[\/／]?\s*侧宽\s*[：:，,]?\s*(\d+(?:\.\d+)?)",
            r"底部宽度\s*[：:，,]?\s*(\d+(?:\.\d+)?)",
            r"侧宽\s*[：:，,]?\s*(\d+(?:\.\d+)?)",
            r"宽\s*[：:，,]?\s*(\d+(?:\.\d+)?)\s*(?:cm|CM|厘米)?",
        ],
        blob,
    )
    parsed.front_pocket_height = _first_float(
        [
            r"前幅[^，,。；;\n]{0,24}(?:大面积)?外贴袋[^0-9]{0,12}(?:约)?(\d+(?:\.\d+)?)\s*(?:cm|CM)?\s*高",
            r"前幅[^，,。；;\n]{0,24}(?:大面积)?外贴袋[^0-9]{0,12}高(?:度)?\s*[：:，,]?\s*(\d+(?:\.\d+)?)",
            r"前幅外贴袋高度\s*[：:，,]?\s*(\d+(?:\.\d+)?)",
        ],
        blob,
    )
    parsed.side_pocket_height = _first_float(
        [
            r"侧面外袋高度\s*[：:，,]?\s*(\d+(?:\.\d+)?)",
            r"左右侧面外贴袋[^0-9]{0,12}(?:约)?(\d+(?:\.\d+)?)\s*(?:cm|CM)?\s*高",
            r"侧(?:面|外)?[^，,。；;\n]{0,20}外贴袋[^0-9]{0,12}高(?:度)?\s*[：:，,]?\s*(\d+(?:\.\d+)?)",
        ],
        blob,
    )
    trolley_pair = re.search(
        r"后幅[^，,。；;\n]{0,80}(?:横向贴片\s*[\/／]\s*拉杆套|拉杆套|横向贴片)"
        r"[^0-9]{0,8}宽(?:度)?\s*[：:，,]?\s*(\d+(?:\.\d+)?)[^高]{0,40}高(?:度)?\s*[：:，,]?\s*(\d+(?:\.\d+)?)",
        blob,
        re.I,
    )
    if trolley_pair:
        parsed.trolley_sleeve_width = float(trolley_pair.group(1))
        parsed.trolley_sleeve_height = float(trolley_pair.group(2))
    else:
        parsed.trolley_sleeve_width = _first_float(
            [
                r"后幅横向贴片\s*[\/／]\s*拉杆套宽度\s*[：:，,]?\s*(\d+(?:\.\d+)?)",
                r"后幅[^，,。；;\n]{0,24}(?:横向贴片\s*[\/／]\s*拉杆套|拉杆套|横向贴片)[^0-9]{0,12}宽(?:度)?\s*[：:，,]?\s*(\d+(?:\.\d+)?)",
                r"(?:拉杆套|后幅横向贴片)[^0-9]{0,12}宽(?:度)?\s*[：:，,]?\s*(\d+(?:\.\d+)?)",
            ],
            blob,
        )
        parsed.trolley_sleeve_height = _first_float(
            [
                r"后幅横向贴片高度\s*[：:，,]?\s*(\d+(?:\.\d+)?)",
                r"后幅[^，,。；;\n]{0,80}高(?:度)?\s*[：:，,]?\s*(\d+(?:\.\d+)?)",
                r"(?:拉杆套|后幅横向贴片)[^0-9]{0,12}高(?:度)?\s*[：:，,]?\s*(\d+(?:\.\d+)?)",
            ],
            blob,
        )
    pu_match = re.search(
        r"底部\s*PU[^0-9]{0,24}(\d+(?:\.\d+)?)\s*[×xX*]\s*(\d+(?:\.\d+)?)",
        blob,
        re.I,
    )
    if pu_match:
        parsed.bottom_pu_length = float(pu_match.group(1))
        parsed.bottom_pu_width = float(pu_match.group(2))

    for key, pattern in (
        ("front_pocket", r"前幅[^，,。；;\n]{0,20}外贴袋|前幅大面积外贴袋"),
        ("side_pocket", r"侧面外袋|左右侧面外贴袋|侧(?:面|外)?外贴袋"),
        ("trolley_sleeve", r"拉杆套|后幅横向贴片|横向贴片"),
        ("bottom_pu", r"底部\s*PU|PU\s*片|底部PU"),
        ("bottom_compartment", r"底部独立仓|独立仓"),
        ("body", r"包身|前片|后片|底片|侧片|横向长度"),
    ):
        if _remark_mentions(blob, pattern):
            parsed.mentions.add(key)
    return parsed


def _parsed_to_structure_dims(parsed: ParsedMaterialRemark) -> tuple[float, float, float] | None:
    if parsed.body_length and parsed.body_height and parsed.body_width:
        return parsed.body_length, parsed.body_height, parsed.body_width
    return None


def _parse_explicit_lwh(blob: str) -> tuple[float, float, float] | None:
    text = str(blob or "").strip()
    if not text:
        return None
    parsed = _parse_material_remark(text)
    dims = _parsed_to_structure_dims(parsed)
    if dims:
        return dims
    match_len = _H_LEN_RE.search(text)
    match_h = _H_HEIGHT_RE.search(text)
    match_w = _H_WIDTH_RE.search(text)
    if match_len and match_h and match_w:
        return float(match_len.group(1)), float(match_h.group(1)), float(match_w.group(1))
    return None


def _parse_dim_pair(blob: str) -> tuple[float, float] | None:
    text = str(blob or "").strip()
    if not text:
        return None
    match = _DIM_PAIR_RE.search(text)
    if match:
        return float(match.group(1)), float(match.group(2))
    return None


def _compute_area(
    formula_key: str,
    *,
    length: float,
    width: float,
    height: float,
    qty: int = 1,
    pair_l: float | None = None,
    pair_w: float | None = None,
) -> tuple[float | None, float | None]:
    """返回 (unit_area_cm2, total_area_cm2)。"""
    q = max(1, qty)
    if formula_key == "panel":
        unit = length * height
    elif formula_key == "bottom":
        unit = length * width
    elif formula_key == "side":
        unit = width * height
    elif formula_key == "perimeter":
        unit = 2 * (length + width) * height
        q = 1
    elif formula_key == "perimeter_with_bottom":
        unit = 2 * (length + width) * height + length * width
        q = 1
    elif formula_key == "pair_size":
        if pair_l is None or pair_w is None:
            return None, None
        unit = pair_l * pair_w
    else:
        return None, None
    unit_r = round(unit, 2)
    return unit_r, round(unit_r * q, 2)


def _cm2_to_m2(cm2: float | None) -> float | None:
    if cm2 is None:
        return None
    return round(float(cm2) / 10_000.0, 6)


def _fmt_m2_display(m2: float | None, *, decimals: int = 2) -> str:
    if m2 is None:
        return "—"
    return f"{m2:.{decimals}f}"


def _fmt_piece_area_display(m2: float | None) -> str:
    if m2 is None:
        return ""
    text = f"{float(m2):.6f}".rstrip("0").rstrip(".")
    return f"{text}m²"


def _fmt_piece_qty_display(qty: float | int | None) -> str:
    if qty is None:
        return "无"
    try:
        qty_num = float(qty)
    except (TypeError, ValueError):
        return "无"
    if qty_num <= 0:
        return "无"
    return _fmt_dim(qty_num)


def _piece_qty_number(piece: dict[str, Any]) -> float | None:
    try:
        qty = float(piece.get("qty"))
    except (TypeError, ValueError):
        return None
    return qty if qty > 0 else None


def _finalize_piece(piece: dict[str, Any]) -> dict[str, Any]:
    unit_cm2 = piece.get("unit_area_cm2")
    total_cm2 = piece.get("total_area_cm2")
    piece["unit_area_m2"] = _cm2_to_m2(unit_cm2) if unit_cm2 is not None else None
    piece["total_area_m2"] = _cm2_to_m2(total_cm2) if total_cm2 is not None else None
    piece["formula"] = piece.get("formula_text") or piece.get("formula_key") or ""
    qty = _piece_qty_number(piece)
    if piece.get("status") == "pending":
        missing_qty = qty is None
        missing_size = total_cm2 is None
        if missing_qty:
            piece["quantity_display"] = "缺少片数"
        else:
            piece["quantity_display"] = _fmt_piece_qty_display(qty)
        if missing_qty and missing_size:
            piece["subtotal_display"] = "缺少片数/尺寸"
        elif missing_qty:
            piece["subtotal_display"] = "缺少片数"
        elif missing_size:
            piece["subtotal_display"] = "缺少尺寸"
        else:
            piece["subtotal_display"] = _fmt_piece_area_display(piece.get("total_area_m2"))
        note = str(piece.get("note") or "").strip()
        missing_note = "缺少片数" if missing_qty else "缺少尺寸"
        if missing_note not in note:
            piece["note"] = f"{note}；{missing_note}，待复核" if note else f"{missing_note}，待复核"
    elif qty is not None:
        piece["quantity_display"] = _fmt_piece_qty_display(qty)
        piece["subtotal_display"] = _fmt_piece_area_display(piece.get("total_area_m2")) or "缺少尺寸"
    else:
        piece["quantity_display"] = "缺少片数"
        piece["subtotal_display"] = "缺少片数"
    if piece.get("note") is None:
        piece["note"] = ""
    return _maybe_hide_formula_display(piece)


def _finalize_pieces(pieces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _dedupe_merge_pieces([_finalize_piece(p) for p in pieces])


def _piece_merge_key(piece: dict[str, Any]) -> tuple[str, str, str, str]:
    name = re.sub(r"\s+", "", str(piece.get("piece") or "")).lower()
    formula = str(piece.get("formula_key") or piece.get("formula") or piece.get("formula_text") or "").strip()
    size = re.sub(r"\s+", "", str(piece.get("size_text") or "")).lower()
    unit_area = str(piece.get("unit_area_cm2") or "")
    return name, formula, size, unit_area


def _source_rank(source: object) -> int:
    text = str(source or "").lower()
    if "field" in text or "材料明细" in text:
        return 4
    if "remark" in text:
        return 3
    if "结构" in text or "structure" in text:
        return 2
    if "ai" in text:
        return 1
    return 0


def _merge_piece_pair(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    base_qty = _piece_qty_number(base)
    in_qty = _piece_qty_number(incoming)
    if base_qty is not None and in_qty is not None:
        out["qty"] = max(base_qty, in_qty)
    elif in_qty is not None:
        out["qty"] = in_qty
    if incoming.get("unit_area_cm2") is not None and out.get("unit_area_cm2") is None:
        out["unit_area_cm2"] = incoming.get("unit_area_cm2")
    if incoming.get("total_area_cm2") is not None and (
        out.get("total_area_cm2") is None or in_qty is not None and in_qty >= (base_qty or 0)
    ):
        out["total_area_cm2"] = incoming.get("total_area_cm2")
    if out.get("unit_area_cm2") is not None and _piece_qty_number(out) is not None:
        out["total_area_cm2"] = round(float(out["unit_area_cm2"]) * float(out["qty"]), 2)
    if str(out.get("status") or "") == "pending" and str(incoming.get("status") or "") != "pending":
        out["status"] = incoming.get("status")
        out["status_label"] = incoming.get("status_label")
    elif str(out.get("status") or "") == str(incoming.get("status") or "") == "pending":
        out["status_label"] = out.get("status_label") or incoming.get("status_label") or "待复核"
    if _source_rank(incoming.get("source")) > _source_rank(out.get("source")):
        out["source"] = incoming.get("source")
    notes = _unique_texts([out.get("note"), incoming.get("note")])
    if len(notes) > 1:
        out["note"] = "；".join(notes)
    elif notes:
        out["note"] = notes[0]
    return _finalize_piece(out)


def _dedupe_merge_pieces(pieces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    index: dict[tuple[str, str, str, str], int] = {}
    for raw in pieces:
        if not isinstance(raw, dict):
            continue
        piece = _finalize_piece(dict(raw))
        key = _piece_merge_key(piece)
        if key in index:
            merged[index[key]] = _merge_piece_pair(merged[index[key]], piece)
            continue
        index[key] = len(merged)
        merged.append(piece)
    return merged


def _build_size_text(
    formula_key: str,
    *,
    length: float,
    width: float,
    height: float,
    qty: int = 1,
    pair_l: float | None = None,
    pair_w: float | None = None,
) -> str:
    l, w, h = _fmt_dim(length), _fmt_dim(width), _fmt_dim(height)
    if formula_key == "panel":
        return f"{l}×{h}×{qty}cm"
    if formula_key == "bottom":
        return f"{l}×{w}×{qty}cm"
    if formula_key == "side":
        return f"{w}×{h}×{qty}cm"
    if formula_key == "perimeter":
        return f"2×({l}+{w})×{h}cm"
    if formula_key == "perimeter_with_bottom":
        return f"2×({l}+{w})×{h} + {l}×{w}cm"
    if formula_key == "pair_size" and pair_l is not None and pair_w is not None:
        return f"{_fmt_dim(pair_l)}×{_fmt_dim(pair_w)}×{qty}cm"
    return "—"


def _area_piece(
    piece: str,
    formula_key: str,
    *,
    length: float = 0.0,
    width: float = 0.0,
    height: float = 0.0,
    pair_l: float | None = None,
    pair_w: float | None = None,
    qty: int = 1,
    source: str = "remark",
    status: str = "ok",
    status_label: str = "已识别",
    note: str = "",
) -> dict[str, Any]:
    unit, total = _compute_area(
        formula_key,
        length=length,
        width=width,
        height=height,
        qty=qty,
        pair_l=pair_l,
        pair_w=pair_w,
    )
    return _finalize_piece(
        {
            "piece": piece,
            "formula_key": formula_key,
            "formula_text": FORMULA_TEXT.get(formula_key, formula_key),
            "size_text": _build_size_text(
                formula_key,
                length=length,
                width=width,
                height=height,
                qty=qty,
                pair_l=pair_l,
                pair_w=pair_w,
            ),
            "qty": qty,
            "unit_area_cm2": unit,
            "total_area_cm2": total,
            "source": source,
            "status": status,
            "status_label": status_label,
            "note": note,
        }
    )


def _inferred_piece_from_part_label(
    label: str,
    *,
    calc_size_text: str = "",
    source: str = "结构推断",
) -> dict[str, Any] | None:
    piece = str(label or "").strip()
    dims = _parse_calc_size_text(calc_size_text)
    if not piece or not dims:
        return None
    l, w, h = dims
    compact = re.sub(r"\s+", "", piece)
    status_label = "推断待核"
    note_prefix = f"按{piece}结构推断"
    if re.search(r"前后|前片.*后片|前后片", compact):
        return _area_piece(
            piece,
            "panel",
            length=l,
            width=w,
            height=h,
            qty=2,
            source=source,
            status="inferred",
            status_label=status_label,
            note=f"{note_prefix}为2片，待复核",
        )
    if re.search(r"左.*右.*侧|左右侧", compact):
        return _area_piece(
            piece,
            "side",
            length=l,
            width=w,
            height=h,
            qty=2,
            source=source,
            status="inferred",
            status_label=status_label,
            note=f"{note_prefix}为2片，待复核",
        )
    if re.search(r"前片|前幅|前面", compact):
        return _area_piece(
            piece,
            "panel",
            length=l,
            width=w,
            height=h,
            qty=1,
            source=source,
            status="inferred",
            status_label=status_label,
            note=f"{note_prefix}为1片，待复核",
        )
    if re.search(r"后片|后幅|后面|拉杆套|贴片", compact):
        return _area_piece(
            piece,
            "panel",
            length=l,
            width=w,
            height=h,
            qty=1,
            source=source,
            status="inferred",
            status_label=status_label,
            note=f"{note_prefix}为1片，待复核",
        )
    if re.search(r"左侧|右侧|侧片|侧面", compact):
        return _area_piece(
            piece,
            "side",
            length=l,
            width=w,
            height=h,
            qty=1,
            source=source,
            status="inferred",
            status_label=status_label,
            note=f"{note_prefix}为1片，待复核",
        )
    if re.search(r"底片|底部|底托|底部PU|PU片|托片", compact, re.I):
        return _area_piece(
            piece,
            "bottom",
            length=l,
            width=w,
            height=h,
            qty=1,
            source=source,
            status="inferred",
            status_label=status_label,
            note=f"{note_prefix}为1片，待复核",
        )
    if re.search(r"手提|提手", compact):
        if re.search(r"一对|左右|两条|2条|2片", compact):
            qty = 2
        else:
            qty = 1
        return _area_piece(
            piece,
            "pair_size",
            pair_l=l,
            pair_w=h,
            qty=qty,
            source=source,
            status="inferred",
            status_label=status_label,
            note=f"{note_prefix}为{qty}片，待复核",
        )
    return None


def _parse_piece_count_near(text: str) -> int | None:
    blob = str(text or "").strip()
    if not blob:
        return None
    match = re.search(r"(?:数量|qty)\s*(\d+(?:\.\d+)?)", blob, re.I)
    if match:
        return max(1, int(float(match.group(1))))
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:\u7247|\u4e2a|\u53ea|pcs?)", blob, re.I)
    if match:
        return max(1, int(float(match.group(1))))
    match = re.search(r"(?:^|[、，,\s])(\d+(?:\.\d+)?)(?:$|[、，,\s])", blob)
    if match:
        return max(1, int(float(match.group(1))))
    if re.fullmatch(r"\d+(?:\.\d+)?", blob):
        return max(1, int(float(blob)))
    if "套" not in blob and not _parse_dim_pair(blob):
        nums = re.findall(r"\d+(?:\.\d+)?", blob)
        if len(nums) == 1:
            return max(1, int(float(nums[0])))
    if not _parse_dim_pair(blob):
        nums = re.findall(r"\d+(?:\.\d+)?", blob)
        residue = re.sub(r"[\d.\s?？]+", "", blob)
        if len(nums) == 1 and len(residue) <= 1 and not re.search(r"\d\s*[gG]\b", blob):
            return max(1, int(float(nums[0])))
    return None


def _remark_list_piece(
    remark: str,
    *,
    label: str,
    aliases: list[str],
    default_qty: int = 1,
) -> dict[str, Any] | None:
    blob = str(remark or "")
    if not blob:
        return None
    alias_re = "|".join(re.escape(x) for x in aliases if x)
    if not alias_re:
        return None
    match = re.search(
        rf"(?:{alias_re})(?P<tail>[^。；;\n]{{0,80}})",
        blob,
        re.I,
    )
    if not match:
        return None
    tail = match.group("tail") or ""
    size_match = _DIM_PAIR_RE.search(tail)
    if not size_match:
        return None
    before_size = tail[: size_match.start()]
    pair_l = float(size_match.group(1))
    pair_w = float(size_match.group(2))
    qty = _parse_piece_count_near(before_size) or default_qty
    return _area_piece(
        label,
        "pair_size",
        pair_l=pair_l,
        pair_w=pair_w,
        qty=qty,
        source="remark",
        status="inferred" if qty == default_qty and not _parse_piece_count_near(before_size) else "ok",
        status_label="规则推断待核" if qty == default_qty and not _parse_piece_count_near(before_size) else "已识别",
        note=f"备注邻近字段解析：{label} {_fmt_dim(pair_l)}×{_fmt_dim(pair_w)}CM，{qty}片",
    )


def _explicit_pieces_from_remark_list(remark: str) -> list[dict[str, Any]]:
    specs = [
        {
            "label": "底部仓",
            "aliases": ["底部仓", "底部独立仓"],
            "default_qty": 1,
        },
        {
            "label": "前幅外贴袋",
            "aliases": ["前幅外贴袋", "前幅大面积外贴袋"],
            "default_qty": 1,
        },
        {
            "label": "侧面上部拉链挡片",
            "aliases": ["侧面上部拉链挡片", "侧面拉链挡片", "拉链挡片"],
            "default_qty": 1,
        },
    ]
    pieces: list[dict[str, Any]] = []
    seen: set[str] = set()
    for spec in specs:
        piece = _remark_list_piece(
            remark,
            label=spec["label"],
            aliases=spec["aliases"],
            default_qty=int(spec["default_qty"]),
        )
        if piece and piece["piece"] not in seen:
            seen.add(str(piece["piece"]))
            pieces.append(piece)
    return pieces


def _row_piece_text(row: dict[str, Any]) -> str:
    return str(
        row.get("piece_part")
        or row.get("part_name")
        or row.get("usage_part")
        or row.get("remark")
        or ""
    ).strip()


def _row_quantity_text(row: dict[str, Any]) -> str:
    for key in ("piece_quantity", "quantity", "qty"):
        text = str(row.get(key) or "").strip()
        if not _display_missing(text):
            return text
    return ""


def _is_dimension_pair_text(text: str) -> bool:
    return bool(_DIM_PAIR_RE.search(str(text or ""))) and not bool(_LWH_TRIPLE_RE.search(str(text or "")))


def _is_piece_count_text(text: str) -> bool:
    blob = str(text or "").strip()
    if not blob:
        return False
    if _parse_dim_pair(blob):
        return False
    if re.search(r"\d\s*[gG]\b", blob):
        return False
    if re.fullmatch(r"\d+(?:\.\d+)?", blob):
        return True
    if re.search(r"(?:数量|qty)\s*\d+(?:\.\d+)?", blob, re.I):
        return True
    return bool(re.search(r"\d+(?:\.\d+)?\s*(?:片|个|只|pcs?)", blob, re.I))


def _is_part_label_text(text: str) -> bool:
    blob = str(text or "").strip()
    if not blob or blob in {"无", "-", "—"}:
        return False
    if _is_dimension_pair_text(blob) or _is_piece_count_text(blob):
        return False
    return bool(re.search(r"包身|主片|底部|底仓|拉杆|贴片|外贴袋|侧|拉链挡片|手提|前幅|后幅", blob))


def _explicit_pieces_from_group_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pieces: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        label = _row_piece_text(row)
        pair = _parse_dim_pair(str(row.get("piece_size") or ""))
        qty = _parse_piece_count_near(_row_quantity_text(row))
        if not label or not pair or qty is None:
            continue
        if _display_missing(label) or _is_dimension_pair_text(label) or _is_piece_count_text(label):
            continue
        key = (label, f"{_fmt_dim(pair[0])}x{_fmt_dim(pair[1])}", qty)
        if key in seen:
            continue
        seen.add(key)
        pieces.append(
            _area_piece(
                label,
                "pair_size",
                pair_l=pair[0],
                pair_w=pair[1],
                qty=qty,
                source="field",
                status="ok",
                status_label="已识别",
                note=f"表格明细解析：{label} {_fmt_dim(pair[0])}×{_fmt_dim(pair[1])}CM，{qty}片",
            )
        )
    pending_label = ""
    pending_qty: int | None = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        text = _row_piece_text(row)
        remark = str(row.get("remark") or "").strip()
        qty = _parse_piece_count_near(_row_quantity_text(row)) or _parse_piece_count_near(text)
        pair = _parse_dim_pair(text)
        if _is_part_label_text(remark):
            pending_label = remark
        if _is_part_label_text(text):
            pending_label = text
            pending_qty = None
            continue
        if qty is not None:
            pending_qty = qty
            if _is_part_label_text(remark):
                pending_label = remark
        if pair:
            label = pending_label or (remark if _is_part_label_text(remark) else "")
            if not label:
                continue
            final_qty = qty or pending_qty or 1
            key = (label, f"{_fmt_dim(pair[0])}x{_fmt_dim(pair[1])}", final_qty)
            if key not in seen:
                seen.add(key)
                pieces.append(
                    _area_piece(
                        label,
                        "pair_size",
                        pair_l=pair[0],
                        pair_w=pair[1],
                        qty=final_qty,
                        source="field",
                        status="ok" if pending_qty or qty else "inferred",
                        status_label="已识别" if pending_qty or qty else "规则推断待核",
                        note=f"相邻行解析：{label} {_fmt_dim(pair[0])}×{_fmt_dim(pair[1])}CM，{final_qty}片",
                    )
                )
            pending_label = ""
            pending_qty = None
    if not pieces:
        for row in rows:
            if not isinstance(row, dict):
                continue
            label = _row_piece_text(row)
            if _display_missing(label):
                label = str(row.get("standard_name_code") or "裁片").strip() or "裁片"
            if _is_dimension_pair_text(label) or _is_piece_count_text(label):
                label = str(row.get("standard_name_code") or "裁片").strip() or "裁片"
            pair = _parse_dim_pair(str(row.get("calculation_size") or ""))
            qty = _parse_piece_count_near(_row_quantity_text(row))
            if not label or not pair or qty is None:
                continue
            key = (label, f"{_fmt_dim(pair[0])}x{_fmt_dim(pair[1])}", qty)
            if key in seen:
                continue
            seen.add(key)
            pieces.append(
                _area_piece(
                    label,
                    "pair_size",
                    pair_l=pair[0],
                    pair_w=pair[1],
                    qty=qty,
                    source="field",
                    status="inferred",
                    status_label="推断待核",
                    note=f"按表格核算尺寸和数量兜底：{label} {_fmt_dim(pair[0])}×{_fmt_dim(pair[1])}CM，{qty}片",
                )
            )
    return pieces


def _pending_piece(
    piece: str,
    hint: str = "待补充",
    *,
    source: str = "remark",
    note: str = "",
) -> dict[str, Any]:
    return _finalize_piece(
        {
            "piece": piece,
            "formula_key": "pending",
            "formula_text": FORMULA_TEXT["pending"],
            "size_text": hint,
            "qty": 0,
            "unit_area_cm2": None,
            "total_area_cm2": None,
            "source": source,
            "status": "pending",
            "status_label": "待复核",
            "note": note or hint,
        }
    )


def _pending_piece_size_substitution(
    *,
    calc_size_text: str = "",
    structure_size_text: str = "",
) -> str:
    calc = str(calc_size_text or "").strip()
    struct = str(structure_size_text or "").strip()
    candidates = [v for v in (calc, struct) if v and v not in {"无", "-", "—"}]
    if candidates:
        return f"{candidates[0]}（覆盖范围/片数待确认）"
    return ""


def _enrich_pending_piece_display(
    pieces: list[dict[str, Any]],
    *,
    calc_size_text: str = "",
    structure_size_text: str = "",
) -> None:
    size_text = _pending_piece_size_substitution(
        calc_size_text=calc_size_text,
        structure_size_text=structure_size_text,
    )
    if not size_text:
        return
    formula_text = "长×宽×片数（覆盖范围待确认）"
    for piece in pieces:
        if not isinstance(piece, dict) or piece.get("status") != "pending":
            continue
        if str(piece.get("formula_text") or piece.get("formula") or "").strip() in {"", "待补充", "pending"}:
            piece["formula_key"] = "pending_area"
            piece["formula_text"] = formula_text
            piece["formula"] = formula_text
        if str(piece.get("size_text") or "").strip() in {"", "待补充", "缺少覆盖范围", "缺少完整尺寸", "待复核"}:
            piece["size_text"] = size_text
        note = str(piece.get("note") or "").strip()
        hint = str(piece.get("size_text") or "").strip()
        if not note:
            piece["note"] = "缺少覆盖范围/片数，待复核"
        elif "缺少" not in note and "待确认" not in note:
            piece["note"] = f"{note}；缺少覆盖范围/片数，待复核"


def _parse_structure_dims(text: str) -> tuple[float, float, float] | None:
    return _parse_explicit_lwh(text)


def _parse_calc_size_text(text: str) -> tuple[float, float, float] | None:
    """仅用于尺寸冲突复核，禁止用于面积计算。"""
    blob = str(text or "").strip()
    if not blob or blob in {"无", "-", "—"}:
        return None
    m = _CALC_SIZE_RE.search(blob.replace("CM", "").replace("cm", ""))
    if not m:
        return None
    return float(m.group(1)), float(m.group(2)), float(m.group(3))


def _size_conflict(calc: tuple[float, float, float] | None, struct: tuple[float, float, float] | None) -> bool:
    """比较三维尺寸是否冲突；按数值 multiset 比较，避免 L/H/W 轴顺序不同误报。"""
    if not calc or not struct:
        return False
    calc_sorted = sorted(calc)
    struct_sorted = sorted(struct)
    return any(abs(a - b) > 1.0 for a, b in zip(calc_sorted, struct_sorted))


def _loss_suggestions_m2(base_m2: float) -> dict[str, float]:
    """展示用含损耗用量（3%），不参与报价计价。"""
    if base_m2 <= 0:
        return {}
    return {"3": round(base_m2 * 1.03, 4)}


def _is_pu_piece_area_material(name: str, mat_type: str) -> bool:
    blob = f"{name} {mat_type}".strip()
    if _PU_PIECE_AREA_RE.search(blob):
        return True
    if re.fullmatch(r"PU料", name.strip(), re.I):
        return True
    if re.search(r"PU料", blob, re.I) and not _BADGE_COUNT_RE.search(blob):
        return True
    return False


def _is_count_badge_material(name: str, mat_type: str, remark: str) -> bool:
    _ = remark
    if _is_pu_piece_area_material(name, mat_type):
        return False
    blob = f"{name} {mat_type}"
    return bool(_BADGE_COUNT_RE.search(blob))


def _classify_material_measure_kind(name: str, mat_type: str, remark: str) -> str:
    name_blob = f"{name} {mat_type}"

    if _is_count_badge_material(name, mat_type, remark):
        return "count"
    if re.search(r"拉链|zipper|#[35]\s*拉链|树脂拉链|尼龙拉链|金属拉链", name_blob, re.I):
        return "count_with_length"
    if re.search(r"加工费|印刷|绣花|车缝费|工艺费", name_blob, re.I):
        return "process"
    if re.search(r"扣具|五金|拉头|d扣|钩扣|调节扣|日字扣|插扣", name_blob, re.I):
        return "count"
    if re.search(r"织带|绳子|包边条|织绳|绳带|拎带", name_blob, re.I):
        return "length"
    if re.search(r"里布|里料|内衬", name_blob, re.I):
        return "lining_area"
    if re.search(r"托料|无纺布|丝绵|珍珠棉|eva|海绵|夹棉|垫底|填充", name_blob, re.I):
        return "padding_area"
    if _is_pu_piece_area_material(name, mat_type) or re.search(r"pu片|\bpu\b", name_blob, re.I):
        return "pu_piece_area"
    if re.search(r"网布|网袋|k080|mesh|侧网|背网", name_blob, re.I):
        return "mesh_area"
    if (
        "面料" in mat_type
        or _is_fabric_material(name, name_blob.lower())
        or re.search(r"记忆布|牛津布|涤纶布|帆布|尼龙布|春亚纺|塔丝隆|仿记忆", name_blob, re.I)
    ):
        return "main_fabric_area"
    return "pending"


def _body_pieces(l: float, h: float, w: float) -> list[dict[str, Any]]:
    return [
        _area_piece(
            "前片",
            "panel",
            length=l,
            width=w,
            height=h,
            qty=1,
            note=f"包身横向长度{_fmt_dim(l)}CM，高度{_fmt_dim(h)}CM",
        ),
        _area_piece(
            "后片",
            "panel",
            length=l,
            width=w,
            height=h,
            qty=1,
            note=f"包身横向长度{_fmt_dim(l)}CM，高度{_fmt_dim(h)}CM",
        ),
        _area_piece(
            "底片",
            "bottom",
            length=l,
            width=w,
            height=h,
            qty=1,
            note=f"底部宽度/侧宽{_fmt_dim(w)}CM",
        ),
        _area_piece(
            "左侧片",
            "side",
            length=l,
            width=w,
            height=h,
            qty=1,
            note=f"侧宽{_fmt_dim(w)}CM，高度{_fmt_dim(h)}CM",
        ),
        _area_piece(
            "右侧片",
            "side",
            length=l,
            width=w,
            height=h,
            qty=1,
            note=f"侧宽{_fmt_dim(w)}CM，高度{_fmt_dim(h)}CM",
        ),
    ]


def _handle_belongs_to_main_fabric(handle_row: dict[str, str], main_name: str, main_remark: str, struct_blob: str) -> bool:
    rname = str(handle_row.get("standard_name_code") or "")
    rtype = str(handle_row.get("type") or "")
    rremark = str(handle_row.get("remark") or "")
    blob = f"{rname} {rtype} {rremark} {main_remark} {struct_blob}"
    if not re.search(r"织带|提手|包布|拎带", f"{rname} {rtype}", re.I):
        return False
    if re.search(r"同(?:色|面料)|记忆布|包布.*{}|{}.*包布".format(re.escape(main_name[:4]), re.escape(main_name[:4])), blob, re.I):
        return True
    if re.search(r"提手包布|手提包布|包布带|提手带.*包布", blob, re.I) and re.search(
        r"记忆布|同面料|{}".format(re.escape(main_name.split("-")[0][:2])), blob, re.I
    ):
        return True
    if re.search(r"提手包布|手提包布", main_remark, re.I) and re.search(r"提手|包布|织带", f"{rname} {rtype}", re.I):
        return True
    return False


def _append_main_fabric_handle_pieces(
    pieces: list[dict[str, Any]],
    hints: list[str],
    *,
    main_name: str,
    main_remark: str,
    material_rows: list[dict[str, str]],
    struct_blob: str,
) -> None:
    if any(p.get("piece") == "手提包布/提手带" for p in pieces):
        return
    for row in material_rows:
        if not _handle_belongs_to_main_fabric(row, main_name, main_remark, struct_blob):
            continue
        rname = str(row.get("standard_name_code") or "").strip()
        rtype = str(row.get("type") or "").strip()
        rremark = str(row.get("remark") or "").strip()
        calc = str(row.get("calculation_size") or "").strip()
        pair = _parse_dim_pair(rremark) or _parse_dim_pair(calc)
        length = _parse_single_length_cm(calc) or _parse_single_length_cm(rremark)
        label = "手提包布/提手带"
        if pair:
            qty = _parse_count_quantity(rremark) or _parse_count_quantity(calc)
            pieces.append(
                _area_piece(
                    label,
                    "pair_size",
                    pair_l=pair[0],
                    pair_w=pair[1],
                    qty=qty,
                    source="field",
                    note=f"来自{rtype}{rname}，备注明确尺寸",
                )
            )
        elif length:
            pieces.append(
                _pending_piece(
                    label,
                    f"单条长度约{_fmt_dim(length)}CM",
                    source="field",
                    note=f"已识别属于{main_name}，单条长度约{length}CM，矩形面积待纸样",
                )
            )
            hints.append(f"{label}：已归入{main_name}，待纸样展开面积")
        else:
            pieces.append(
                _pending_piece(
                    label,
                    "待补充尺寸",
                    source="field",
                    note=f"已识别属于{main_name}，备注未给出可计算尺寸",
                )
            )
            hints.append(f"{label}：已归入{main_name}，待复核尺寸")
        return
    if re.search(r"提手包布|手提包布|提手带.*包布", f"{main_remark}\n{struct_blob}", re.I):
        pieces.append(
            _pending_piece(
                "手提包布/提手带",
                "待补充尺寸",
                note=f"已识别属于{main_name}，备注未给出可计算尺寸",
            )
        )
        hints.append("手提包布/提手带：备注提及但缺少尺寸，待复核")


def _main_fabric_pieces_from_remark(
    remark: str,
    *,
    main_name: str = "",
    material_rows: list[dict[str, str]] | None = None,
    struct_blob: str = "",
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    parsed = _parse_material_remark(remark)
    pieces: list[dict[str, Any]] = []
    covered: list[str] = []
    hints: list[str] = []

    bl, bh, bw = parsed.body_length, parsed.body_height, parsed.body_width
    if bl and bh and bw:
        pieces.extend(_body_pieces(bl, bh, bw))
        covered.extend(["前片", "后片", "底片", "左侧片", "右侧片"])
    elif "body" in parsed.mentions:
        hints.append("包身主体：备注未解析到完整的横向长度×高度×侧宽，待复核")
        pieces.append(_pending_piece("包身主体", "缺少完整尺寸"))

    if parsed.front_pocket_height and bl:
        pieces.append(
            _area_piece(
                "前幅外贴袋",
                "panel",
                length=bl,
                width=bw or 0,
                height=parsed.front_pocket_height,
                qty=1,
                note=f"前幅外贴袋高度{_fmt_dim(parsed.front_pocket_height)}CM",
            )
        )
        covered.append("前幅外贴袋")
    elif "front_pocket" in parsed.mentions:
        hints.append("前幅外贴袋：备注提及但未解析到完整尺寸，待复核")
        pieces.append(_pending_piece("前幅外贴袋", note="前幅外贴袋：备注提及但缺少高度"))
    elif re.search(r"前幅|前片", remark, re.I):
        hints.append("前幅：备注提及但未解析到完整尺寸，待复核")
        pieces.append(_pending_piece("前幅", note="前幅：备注提及但缺少可计算尺寸"))

    if parsed.side_pocket_height and bw:
        pieces.append(
            _area_piece(
                "左侧面外贴袋",
                "side",
                length=bl or 0,
                width=bw,
                height=parsed.side_pocket_height,
                qty=1,
                note=f"侧面外袋高度{_fmt_dim(parsed.side_pocket_height)}CM",
            )
        )
        pieces.append(
            _area_piece(
                "右侧面外贴袋",
                "side",
                length=bl or 0,
                width=bw,
                height=parsed.side_pocket_height,
                qty=1,
                note=f"侧面外袋高度{_fmt_dim(parsed.side_pocket_height)}CM",
            )
        )
        covered.extend(["左侧面外贴袋", "右侧面外贴袋"])
    elif "side_pocket" in parsed.mentions:
        hints.append("侧面外贴袋：备注提及但未解析到完整尺寸，待复核")
        pieces.append(_pending_piece("左侧面外贴袋"))
        pieces.append(_pending_piece("右侧面外贴袋"))

    if parsed.trolley_sleeve_width and parsed.trolley_sleeve_height:
        pieces.append(
            _area_piece(
                "后幅拉杆套",
                "pair_size",
                pair_l=parsed.trolley_sleeve_width,
                pair_w=parsed.trolley_sleeve_height,
                qty=1,
                note=f"后幅拉杆套宽{_fmt_dim(parsed.trolley_sleeve_width)}CM，高{_fmt_dim(parsed.trolley_sleeve_height)}CM",
            )
        )
        covered.append("后幅拉杆套")
    elif "trolley_sleeve" in parsed.mentions:
        hints.append("后幅拉杆套：备注提及但未解析到宽×高，待复核")
        pieces.append(_pending_piece("后幅拉杆套"))

    if _BACK_POCKET_RE.search(remark):
        if bl and bh:
            match_h = re.search(r"后幅[^，,。；;\n]{0,20}高(?:度)?\s*[：:，,]?\s*(\d+(?:\.\d+)?)", remark, re.I)
            back_h = float(match_h.group(1)) if match_h else None
            if back_h:
                pieces.append(
                    _area_piece(
                        "后幅外贴袋（面）",
                        "panel",
                        length=bl,
                        width=bw or 0,
                        height=back_h,
                        qty=1,
                        note=f"后幅外贴袋高度{_fmt_dim(back_h)}CM",
                    )
                )
                covered.append("后幅外贴袋")
            else:
                hints.append("后幅外贴袋：备注提及但未解析到高度，待复核")
                pieces.append(_pending_piece("后幅外贴袋（面）"))
        else:
            hints.append("后幅外贴袋：缺少包身横向长度，待复核")

    if "bottom_compartment" in parsed.mentions:
        hints.append("底部独立仓是否分片，结构未写明，待复核")

    if main_name and material_rows is not None:
        _append_main_fabric_handle_pieces(
            pieces,
            hints,
            main_name=main_name,
            main_remark=remark,
            material_rows=material_rows,
            struct_blob=struct_blob,
        )

    explicit_pieces = _explicit_pieces_from_remark_list(remark)
    if explicit_pieces:
        explicit_names = {str(p.get("piece") or "") for p in explicit_pieces}
        pieces = [
            p
            for p in pieces
            if not (p.get("status") == "pending" and str(p.get("piece") or "") in explicit_names)
        ]
        existing_names = {str(p.get("piece") or "") for p in pieces}
        for piece in explicit_pieces:
            name = str(piece.get("piece") or "")
            if name and name not in existing_names:
                pieces.append(piece)
                covered.append(name)
                existing_names.add(name)

    return pieces, covered, hints


def _lining_pieces_from_remark(remark: str) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    blob = str(remark or "").strip()
    pieces: list[dict[str, Any]] = []
    covered: list[str] = []
    hints: list[str] = []
    if not blob or blob in {"无", "-", "—"}:
        hints.append(
            "缺少里布覆盖范围，需确认：整圈+底片 / 周围立面 / 底里片 / 前后片 / 侧片 / 内袋 / 隔层。"
        )
        pieces.append(_pending_piece("里布覆盖范围", "缺少覆盖范围"))
        return pieces, covered, hints

    dims = _parse_explicit_lwh(blob)
    l_, h_, w_ = dims if dims else (0.0, 0.0, 0.0)

    if re.search(r"整圈\s*[+＋]\s*底片|全包内衬|里布全包|内衬一圈加底|整圈内衬\s*[+＋]\s*底片?", blob, re.I):
        if dims:
            pieces.append(
                _area_piece(
                    "里布（整圈+底片）",
                    "perimeter_with_bottom",
                    length=l_,
                    width=w_,
                    height=h_,
                    qty=1,
                    status="inferred",
                    status_label="估算待核",
                )
            )
            covered.append("里布整圈+底片")
        else:
            hints.append("整圈+底片：备注未解析到长×宽×高，待复核")
            pieces.append(_pending_piece("里布（整圈+底片）"))
    elif re.search(r"周围|整圈|围片|周围立面", blob, re.I) and not re.search(r"底片|底里", blob, re.I):
        if dims:
            pieces.append(
                _area_piece(
                    "里布（周围立面）",
                    "perimeter",
                    length=l_,
                    width=w_,
                    height=h_,
                    qty=1,
                    status="inferred",
                    status_label="估算待核",
                )
            )
            covered.append("里布周围立面")
        else:
            hints.append("周围立面：备注未解析到长×宽×高，待复核")
            pieces.append(_pending_piece("里布（周围立面）"))
    elif re.search(r"底里片|底片", blob, re.I):
        pair = _parse_dim_pair(blob)
        if pair:
            pieces.append(
                _area_piece("里布底片", "pair_size", pair_l=pair[0], pair_w=pair[1], qty=1)
            )
            covered.append("里布底片")
        elif dims:
            pieces.append(
                _area_piece("里布底片", "bottom", length=l_, width=w_, height=h_, qty=1)
            )
            covered.append("里布底片")
        else:
            hints.append("底里片：缺少尺寸，待复核")
            pieces.append(_pending_piece("里布底片"))
    elif re.search(r"前后片|前后夹棉", blob, re.I) and dims:
        pieces.append(
            _area_piece(
                "里布前后片",
                "panel",
                length=l_,
                width=w_,
                height=h_,
                qty=2,
                status="inferred",
                status_label="估算待核",
            )
        )
        covered.append("里布前后片")
    elif re.search(r"左右侧|两侧|侧片|侧围", blob, re.I) and dims:
        pieces.append(
            _area_piece(
                "里布侧片",
                "side",
                length=l_,
                width=w_,
                height=h_,
                qty=2,
                status="inferred",
                status_label="估算待核",
            )
        )
        covered.append("里布侧片")
    elif re.search(r"里布|里料|内衬", blob, re.I):
        hints.append(
            "缺少里布覆盖范围，需确认：整圈+底片 / 周围立面 / 底里片 / 前后片 / 侧片 / 内袋 / 隔层。"
        )
        pieces.append(_pending_piece("里布覆盖范围", "缺少覆盖范围"))
    return pieces, covered, hints


def _padding_pieces_from_remark(remark: str) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    blob = str(remark or "").strip()
    pieces: list[dict[str, Any]] = []
    covered: list[str] = []
    hints: list[str] = []
    if not blob or blob in {"无", "-", "—"}:
        hints.append(
            "缺少覆盖范围，需确认：底片 / 前后片 / 侧片 / 整圈+底片 / 隔层 / 局部垫片。"
        )
        pieces.append(_pending_piece("内部托料", "缺少覆盖范围"))
        return pieces, covered, hints

    dims = _parse_explicit_lwh(blob)
    l_, h_, w_ = dims if dims else (0.0, 0.0, 0.0)
    pair = _parse_dim_pair(blob)

    if pair and re.search(r"尺寸|托片|垫片|底托", blob, re.I):
        label = "底部托片" if re.search(r"底", blob, re.I) else "托料裁片"
        fk = "bottom" if re.search(r"底", blob, re.I) else "pair_size"
        if fk == "bottom":
            pieces.append(
                _area_piece(label, "bottom", length=pair[0], width=pair[1], height=h_, qty=1)
            )
        else:
            pieces.append(_area_piece(label, "pair_size", pair_l=pair[0], pair_w=pair[1], qty=1))
        covered.append(label)
        return pieces, covered, hints

    if re.search(r"整圈\s*[+＋]\s*底片|整圈内衬\s*[+＋]\s*底片|内衬一圈加底", blob, re.I):
        if dims:
            pieces.append(
                _area_piece(
                    "整圈托料+底片",
                    "perimeter_with_bottom",
                    length=l_,
                    width=w_,
                    height=h_,
                    qty=1,
                    status="inferred",
                    status_label="估算待核",
                )
            )
            covered.append("整圈托料+底片")
        else:
            hints.append("整圈+底片：缺少长×宽×高，待复核")
            pieces.append(_pending_piece("整圈托料+底片"))
        return pieces, covered, hints

    if re.search(r"整圈|周围|围片|内衬一圈", blob, re.I) and not re.search(
        r"整圈\s*[+＋]\s*底片|整圈内衬\s*[+＋]\s*底片", blob, re.I
    ):
        if dims:
            pieces.append(
                _area_piece(
                    "围片托料",
                    "perimeter",
                    length=l_,
                    width=w_,
                    height=h_,
                    qty=1,
                    status="inferred",
                    status_label="估算待核",
                )
            )
            covered.append("围片托料")
        else:
            hints.append("围片托料：缺少长×宽×高，待复核")
            pieces.append(_pending_piece("围片托料"))
        return pieces, covered, hints

    if re.search(r"底部|底托|底片|垫底", blob, re.I):
        if pair:
            pieces.append(
                _area_piece("底部托片", "pair_size", pair_l=pair[0], pair_w=pair[1], qty=1)
            )
            covered.append("底部托片")
        elif dims:
            pieces.append(
                _area_piece("底部托片", "bottom", length=l_, width=w_, height=h_, qty=1)
            )
            covered.append("底部托片")
        else:
            hints.append("底部托片：缺少尺寸，待复核")
            pieces.append(_pending_piece("底部托片"))
        return pieces, covered, hints

    if re.search(r"前后片|前后夹棉", blob, re.I):
        if dims:
            pieces.append(
                _area_piece(
                    "前后夹棉",
                    "panel",
                    length=l_,
                    width=w_,
                    height=h_,
                    qty=2,
                    status="inferred",
                    status_label="估算待核",
                )
            )
            covered.append("前后夹棉")
        else:
            hints.append("前后夹棉：缺少尺寸，待复核")
            pieces.append(_pending_piece("前后夹棉"))
        return pieces, covered, hints

    if re.search(r"左右侧|两侧|侧片|侧围", blob, re.I):
        if dims:
            pieces.append(
                _area_piece(
                    "侧围托料",
                    "side",
                    length=l_,
                    width=w_,
                    height=h_,
                    qty=2,
                    status="inferred",
                    status_label="估算待核",
                )
            )
            covered.append("侧围托料")
        else:
            hints.append("侧围托料：缺少尺寸，待复核")
            pieces.append(_pending_piece("侧围托料"))
        return pieces, covered, hints

    if pair:
        pieces.append(_area_piece("托料裁片", "pair_size", pair_l=pair[0], pair_w=pair[1], qty=1))
        covered.append("托料裁片")
        return pieces, covered, hints

    hints.append(
        "缺少覆盖范围，需确认：底片 / 前后片 / 侧片 / 整圈+底片 / 隔层 / 局部垫片。"
    )
    pieces.append(_pending_piece("内部托料", "缺少覆盖范围"))
    return pieces, covered, hints


def _parse_bottom_compartment_piece(blob: str) -> tuple[float, float, int] | None:
    """解析「底部独立仓围片」明确尺寸，返回 (长, 宽, 片数)。"""
    text = str(blob or "").strip()
    if not text:
        return None
    patterns = [
        r"底部独立仓围片[^0-9]{0,12}尺寸?\s*[：:，,]?\s*(\d+(?:\.\d+)?)\s*[×xX*]\s*(\d+(?:\.\d+)?)",
        r"底部独立仓[^0-9]{0,20}围片[^0-9]{0,12}尺寸?\s*[：:，,]?\s*(\d+(?:\.\d+)?)\s*[×xX*]\s*(\d+(?:\.\d+)?)",
        r"独立仓围片[^0-9]{0,12}尺寸?\s*[：:，,]?\s*(\d+(?:\.\d+)?)\s*[×xX*]\s*(\d+(?:\.\d+)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if not match:
            continue
        length = float(match.group(1))
        width = float(match.group(2))
        tail = text[match.start() : match.end() + 24]
        qty_match = re.search(r"(\d+)\s*片", tail, re.I)
        qty = max(1, int(qty_match.group(1))) if qty_match else 1
        return length, width, qty
    return None


def _pu_pieces_from_remark(remark: str, *, full_blob: str = "") -> tuple[list[dict[str, Any]], list[str], list[str]]:
    parsed = _parse_material_remark(remark)
    if not (parsed.bottom_pu_length and parsed.bottom_pu_width) and full_blob:
        fallback = _parse_material_remark(full_blob)
        if fallback.bottom_pu_length and fallback.bottom_pu_width:
            parsed.bottom_pu_length = fallback.bottom_pu_length
            parsed.bottom_pu_width = fallback.bottom_pu_width
            parsed.mentions.update(fallback.mentions)
    pieces: list[dict[str, Any]] = []
    covered: list[str] = []
    hints: list[str] = []
    search_blob = f"{remark}\n{full_blob}"
    pair = _parse_dim_pair(remark) or _parse_dim_pair(full_blob)
    qty = _parse_explicit_piece_count(search_blob)
    qty_inferred = qty is None
    final_qty = qty or 1

    if parsed.bottom_pu_length and parsed.bottom_pu_width:
        pieces.append(
            _area_piece(
                "底部 PU 片",
                "pair_size",
                pair_l=parsed.bottom_pu_length,
                pair_w=parsed.bottom_pu_width,
                qty=final_qty,
                status="inferred" if qty_inferred else "ok",
                status_label="AI推断待核" if qty_inferred else "已识别",
                note="未识别明确片数，按单个底部 PU 片推断 1 片，待复核" if qty_inferred else "",
            )
        )
        covered.append("底部 PU 片")
    elif pair:
        pieces.append(
            _area_piece(
                "底部 PU 片",
                "pair_size",
                pair_l=pair[0],
                pair_w=pair[1],
                qty=final_qty,
                status="inferred" if qty_inferred else "ok",
                status_label="AI推断待核" if qty_inferred else "已识别",
                note="未识别明确片数，按单个底部 PU 片推断 1 片，待复核" if qty_inferred else "",
            )
        )
        covered.append("底部 PU 片")
    elif "bottom_pu" in parsed.mentions or re.search(r"底部\s*PU|PU\s*片|底部PU|底部隔离", search_blob, re.I):
        hints.append("底部 PU 片：备注提及但未解析到尺寸，待复核")
        pieces.append(_pending_piece("底部 PU 片"))

    compartment = _parse_bottom_compartment_piece(remark) or _parse_bottom_compartment_piece(full_blob)
    if compartment:
        cl, cw, cqty = compartment
        pieces.append(
            _area_piece(
                "底部独立仓围片",
                "pair_size",
                pair_l=cl,
                pair_w=cw,
                qty=cqty,
            )
        )
        covered.append("底部独立仓围片")
    elif re.search(r"底部独立仓|独立仓围片|独立仓", search_blob, re.I):
        hints.append("底部独立仓围片：结构提及但未解析到尺寸，待复核")
        pieces.append(_pending_piece("底部独立仓围片"))

    if covered:
        hints.append("可能与主料底片重复，待纸样复核")

    return pieces, covered, hints


def _mesh_pieces_from_remark(remark: str, *, full_blob: str = "") -> tuple[list[dict[str, Any]], list[str], list[str]]:
    blob = f"{remark}\n{full_blob}".strip()
    pieces: list[dict[str, Any]] = []
    covered: list[str] = []
    hints: list[str] = []
    if not re.search(r"网袋|网兜|侧网|背网|网布", blob, re.I):
        hints.append("需补充：网袋位置、尺寸、片数")
        pieces.append(_pending_piece("网袋裁片", "缺少网布位置与尺寸"))
        return pieces, covered, hints
    pair = _parse_dim_pair(blob)
    dims = _parse_explicit_lwh(blob)
    if pair:
        label = "网袋裁片" if "网袋" in blob else "网布裁片"
        pieces.append(_area_piece(label, "pair_size", pair_l=pair[0], pair_w=pair[1], qty=1))
        covered.append(label)
    elif dims:
        l_, h_, w_ = dims
        pieces.append(
            _area_piece("网布裁片", "panel", length=l_, width=w_, height=h_, qty=1, status="inferred", status_label="估算待核")
        )
        covered.append("网布裁片")
    else:
        hints.append("网袋（结构提及，尺寸待核）")
        pieces.append(_pending_piece("网袋裁片"))
    return pieces, covered, hints


def _parse_single_length_cm(text: str) -> float | None:
    blob = str(text or "").strip()
    if not blob or blob in {"无", "-", "—"}:
        return None
    # 纯数量备注（2个、2条、1）不是长度规格
    if re.fullmatch(r"\d+(?:\.\d+)?\s*(?:个|件|条|pcs|PCS)?\s*$", blob, re.I):
        return None
    m_m = re.search(r"(\d+(?:\.\d+)?)\s*m\b", blob, re.I)
    if m_m:
        return round(float(m_m.group(1)) * 100, 2)
    m_cm = re.search(r"(\d+(?:\.\d+)?)\s*(?:cm|CM|厘米)\b", blob, re.I)
    if m_cm:
        return round(float(m_cm.group(1)), 2)
    # 无单位数字仅在 calc_size 等明确长度字段使用；纯数字不当作 cm
    return None


def _parse_count_quantity(remark: str, *, default: int = 1) -> int:
    blob = str(remark or "").strip()
    if not blob or blob in {"无", "-", "—"}:
        return default
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:条|pcs|PCS|个|件|片)", blob, re.I)
    if m:
        return max(1, int(round(float(m.group(1)))))
    if re.fullmatch(r"\d+", blob):
        return max(1, int(blob))
    return default


def _parse_explicit_piece_count(text: str) -> int | None:
    blob = str(text or "").strip()
    if not blob:
        return None
    patterns = (
        r"覆盖\s*(\d+(?:\.\d+)?)",
        r"片数\s*[：:]?\s*(\d+(?:\.\d+)?)",
        r"数量\s*[：:]?\s*(\d+(?:\.\d+)?)\s*片?",
        r"(\d+(?:\.\d+)?)\s*片",
    )
    for pattern in patterns:
        match = re.search(pattern, blob, re.I)
        if match:
            return max(1, int(round(float(match.group(1)))))
    return None


_SIMPLE_PAD_PIECE_RE = re.compile(r"底部托片|底部\s*PU\s*片|托料裁片|单片托", re.I)
_FULL_CIRCLE_PAD_PIECE_RE = re.compile(r"整圈托料\s*[+＋]\s*底片|整圈内衬\s*[+＋]\s*底片", re.I)
_SIMPLE_PAD_NOTE = "按底部托片核算，厚度/高度仅作规格说明，不参与面积计算。"


def _maybe_hide_formula_display(piece: dict[str, Any]) -> dict[str, Any]:
    name = str(piece.get("piece") or "")
    formula_key = str(piece.get("formula_key") or "")
    if formula_key in {"bottom", "pair_size"} and _SIMPLE_PAD_PIECE_RE.search(name):
        if not str(piece.get("note") or "").strip():
            piece["note"] = _SIMPLE_PAD_NOTE
    return piece


def _parse_zipper_slots(blob: str, parsed: ParsedMaterialRemark) -> list[dict[str, Any]]:
    text = str(blob or "").strip()
    if not text:
        return []
    body_l = parsed.body_length
    body_w = parsed.body_width
    slots: list[dict[str, Any]] = []

    if re.search(r"U型|U\s*型|绕口|环绕|绕整个包口|一圈拉链", text, re.I):
        if body_l is not None and body_w is not None:
            slots.append(
                {
                    "slot": "u_wrap",
                    "length_cm": round(2 * (body_l + body_w), 2),
                    "label": "U型/绕口拉链",
                }
            )
        return slots

    combined = re.search(
        r"主仓[^。；;\n]{0,48}底仓[^。；;\n]{0,48}各[^。；;\n]{0,10}条拉链"
        r"|主仓[^。；;\n]{0,48}拉链[^。；;\n]{0,48}底仓[^。；;\n]{0,48}拉链"
        r"|主仓和底仓各一条拉链",
        text,
        re.I,
    )
    if combined and body_l is not None:
        return [
            {"slot": "main", "length_cm": body_l, "label": "主仓拉链"},
            {"slot": "bottom", "length_cm": body_l, "label": "底仓拉链"},
        ]

    if re.search(r"主仓|主袋|主拉链|顶部开口|主开口|包口拉链", text, re.I) and body_l is not None:
        slots.append({"slot": "main", "length_cm": body_l, "label": "主仓拉链"})
    if re.search(r"底仓|底部独立仓|底袋拉链|底仓拉链", text, re.I):
        open_len = body_l if body_l is not None else body_w
        if open_len is not None:
            slots.append({"slot": "bottom", "length_cm": open_len, "label": "底仓拉链"})
    if re.search(r"前袋|前贴袋|前幅外贴袋|正面[^。；;\n]{0,12}拉链", text, re.I) and body_l is not None:
        slots.append({"slot": "front_pocket", "length_cm": body_l, "label": "前袋拉链"})
    if re.search(r"后袋|后贴袋", text, re.I) and body_l is not None:
        slots.append({"slot": "back_pocket", "length_cm": body_l, "label": "后袋拉链"})
    if re.search(r"侧袋[^。；;\n]{0,20}拉链|侧[^。；;\n]{0,12}拉链|侧面[^。；;\n]{0,12}拉链", text, re.I):
        open_len = body_w if body_w is not None else body_l
        if open_len is not None:
            slots.append({"slot": "side_pocket", "length_cm": open_len, "label": "侧袋拉链"})

    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for slot in slots:
        key = str(slot.get("slot") or "")
        if key and key not in seen:
            seen.add(key)
            unique.append(slot)
    return unique


def _has_explicit_zipper_position(name: str, remark: str) -> bool:
    """材料行是否明确限定拉链所在位置（材料名中的泛化「拉链」不算）。"""
    blob = f"{name}\n{remark}"
    return bool(
        re.search(
            r"主仓(?:拉链)?|主袋(?:拉链)?|主拉链"
            r"|底仓(?:拉链)?|底部独立仓|底袋拉链"
            r"|前袋(?:拉链)?|前贴袋|前幅外贴袋"
            r"|后袋(?:拉链)?|后贴袋"
            r"|侧袋(?:拉链)?|侧面外袋"
            r"|U型|U\s*型|绕口|环绕",
            blob,
            re.I,
        )
    )


def _match_zipper_row_to_slots(
    name: str,
    remark: str,
    slots: list[dict[str, Any]],
    remark_qty: int,
) -> tuple[list[dict[str, Any]], int]:
    if not slots:
        return [], max(remark_qty, 1)

    if not _has_explicit_zipper_position(name, remark):
        if len(slots) > 1:
            return slots, len(slots)
        return slots, remark_qty or 1

    blob = f"{name}\n{remark}"
    slot_map = {str(s.get("slot") or ""): s for s in slots}
    for key, pattern in (
        ("main", r"主仓(?:拉链)?|主袋(?:拉链)?|主拉链"),
        ("bottom", r"底仓(?:拉链)?|底部独立仓|底袋拉链"),
        ("front_pocket", r"前袋(?:拉链)?|前贴袋|前幅外贴袋"),
        ("back_pocket", r"后袋(?:拉链)?|后贴袋"),
        ("side_pocket", r"侧袋(?:拉链)?|侧面外袋"),
        ("u_wrap", r"U型|U\s*型|绕口|环绕"),
    ):
        if re.search(pattern, blob, re.I) and key in slot_map:
            return [slot_map[key]], remark_qty or 1

    if len(slots) > 1:
        return slots, len(slots)
    return slots, remark_qty or 1


def _zipper_measure_summary_from_structure(
    name: str,
    remark: str,
    struct_blob: str,
    *,
    zipper_row_index: int = 0,
    total_zipper_rows: int = 1,
) -> tuple[dict[str, Any], list[str]]:
    review_hints: list[str] = []
    parsed = _parse_material_remark(struct_blob)
    slots = _parse_zipper_slots(struct_blob, parsed)
    remark_qty = _parse_count_quantity(remark, default=0)
    if remark_qty <= 0:
        remark_qty = 1

    if total_zipper_rows > 1 and len(slots) > 1 and not _has_explicit_zipper_position(
        name, remark
    ):
        idx = min(zipper_row_index, len(slots) - 1)
        matched = [slots[idx]]
        qty = remark_qty
    else:
        matched, qty = _match_zipper_row_to_slots(name, remark, slots, remark_qty)

    if not matched:
        review_hints.append("拉链尺寸待补充")
        return (
            {
                "measure_unit": "条",
                "quantity": remark_qty,
                "spec_text": "拉链尺寸待补充",
                "structure_size_text": "拉链尺寸待补充",
                "status_label": "按条计量",
                "structure_derived": False,
                "pending_size": True,
            },
            review_hints,
        )

    lengths = {float(s["length_cm"]) for s in matched}
    if len(matched) == 1:
        spec_text = f"{_fmt_dim(matched[0]['length_cm'])}CM/条"
        unit_length_cm = matched[0]["length_cm"]
    elif len(lengths) == 1:
        common_len = next(iter(lengths))
        spec_text = f"{_fmt_dim(common_len)}CM/条"
        unit_length_cm = common_len
    else:
        spec_text = "、".join(f"{s['label']}{_fmt_dim(s['length_cm'])}CM" for s in matched)
        unit_length_cm = None

    return (
        {
            "measure_unit": "条",
            "quantity": qty,
            "unit_length_cm": unit_length_cm,
            "spec_text": spec_text,
            "structure_size_text": spec_text,
            "status_label": "按结构推导",
            "structure_derived": True,
            "pending_size": False,
            "zipper_slots": [
                {"label": str(s.get("label") or ""), "length_cm": s["length_cm"]} for s in matched
            ],
        },
        review_hints,
    )


def _parse_badge_count_quantity(remark: str, calc_size_text: str = "") -> int | None:
    for blob in (remark, calc_size_text):
        text = str(blob or "").strip()
        if not text or text in {"无", "-", "—"}:
            continue
        match = re.search(r"(\d+(?:\.\d+)?)\s*(?:个|pcs|PCS|件|只)", text, re.I)
        if match:
            return max(1, int(round(float(match.group(1)))))
        if re.fullmatch(r"\d+", text):
            return max(1, int(text))
    return None


def _badge_measure_summary(name: str, remark: str, calc_size_text: str) -> dict[str, Any]:
    qty = _parse_badge_count_quantity(remark, calc_size_text)
    return {
        "measure_unit": "个",
        "quantity": qty,
        "status_label": "按个计量",
        "is_badge_count": True,
        "badge_name": name,
    }


def _count_measure_summary(remark: str, calc_size_text: str) -> dict[str, Any]:
    """扣具/五金/拉头：仅数量，不解析长度参考。"""
    qty = _parse_count_quantity(remark or calc_size_text, default=1)
    return {
        "measure_unit": "个",
        "quantity": qty,
        "status_label": "按个计量",
    }


def _countable_measure_summary(measure_unit: str, remark: str, calc_size_text: str) -> dict[str, Any]:
    qty = _parse_count_quantity(remark or calc_size_text, default=1)
    length = _parse_single_length_cm(calc_size_text)
    if length is None and measure_unit == "米":
        length = _parse_single_length_cm(remark)
    out: dict[str, Any] = {
        "measure_unit": measure_unit,
        "quantity": qty,
        "status_label": f"按{measure_unit}计量" if measure_unit != "米" else "按长度计量",
    }
    if length is not None:
        out["unit_length_cm"] = length
        out["total_length_cm"] = round(length * qty, 2)
        out["total_length_m"] = round(out["total_length_cm"] / 100, 2)
        out["spec_text"] = f"{_fmt_dim(length)}CM/{measure_unit}"
    return out


def _counted_covered_parts(pieces: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for piece in pieces:
        if piece.get("status") == "pending":
            continue
        if piece.get("total_area_cm2") is None:
            continue
        name = str(piece.get("piece") or "").strip()
        if name and name not in out:
            out.append(name)
    return out


def _pending_part_labels(pieces: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for piece in pieces:
        if piece.get("status") != "pending":
            continue
        name = str(piece.get("piece") or "").strip()
        if name and name not in out:
            out.append(name)
    return out


def _build_display_summary(
    *,
    mat_type: str,
    name: str,
    calc_size_text: str,
    structure_size_text: str,
    total_m2: float | None,
    loss: dict[str, float],
    covered_parts: list[str],
    pending_parts: list[str],
    size_conflict: bool,
    review_hints: list[str],
) -> dict[str, Any]:
    title = f"{mat_type}｜{name}" if mat_type else name
    with_loss: dict[str, str] = {}
    with_loss_raw: dict[str, float] = {}
    if total_m2 and total_m2 > 0:
        for rate in ("3",):
            if rate in loss:
                with_loss_raw[rate] = loss[rate]
                with_loss[rate] = _fmt_m2_display(loss[rate])
    return {
        "title": title,
        "calc_size_text": calc_size_text or "—",
        "structure_size_text": structure_size_text or "—",
        "base_usage_m2": total_m2,
        "base_usage_m2_display": _fmt_m2_display(total_m2, decimals=4).rstrip("0").rstrip(".") if total_m2 else "—",
        "base_usage_m2_rounded": _fmt_m2_display(total_m2) if total_m2 else "—",
        "loss_rates": [3],
        "with_loss_m2": with_loss_raw,
        "with_loss_m2_display": with_loss,
        "covered_parts": covered_parts,
        "pending_parts": pending_parts,
        "size_conflict": size_conflict,
        "review_hints": review_hints,
    }


def _total_area(pieces: list[dict[str, Any]]) -> float:
    return round(
        sum(
            float(p["total_area_cm2"])
            for p in pieces
            if p.get("total_area_cm2") is not None and p.get("status") != "pending"
        ),
        2,
    )


def _collect_material_rows(quote: dict[str, Any]) -> list[dict[str, str]]:
    from admin_bom_requirement_view import _materials_detail_rows

    meta = quote.get("bom_requirement_view") if isinstance(quote.get("bom_requirement_view"), dict) else {}
    rows = _materials_detail_rows(quote, meta if isinstance(meta, dict) else None)
    if rows:
        return rows

    req = quote.get("bom_requirement_view") or {}
    if isinstance(req, dict):
        for section in req.get("sections") or []:
            if not isinstance(section, dict) or str(section.get("key") or "") != "C":
                continue
            dr = section.get("detail_rows")
            if not isinstance(dr, list):
                continue
            out: list[dict[str, str]] = []
            for raw in dr:
                if not isinstance(raw, dict):
                    continue
                name = str(raw.get("standard_name_code") or raw.get("standard_name") or "").strip()
                if not name or name in {"无", "-", "—"}:
                    continue
                out.append(
                    {
                        "type": str(raw.get("type") or ""),
                        "standard_name_code": name,
                        "calculation_size": str(raw.get("calculation_size") or raw.get("calc_size") or ""),
                        "remark": str(raw.get("remark") or ""),
                        "usage": str(raw.get("usage") or raw.get("total_usage") or raw.get("quoted_usage") or ""),
                        "quantity": str(raw.get("quantity") or raw.get("piece_quantity") or raw.get("qty") or ""),
                        "piece_part": str(raw.get("piece_part") or raw.get("part_name") or raw.get("usage_part") or ""),
                        "piece_size": str(raw.get("piece_size") or raw.get("size") or ""),
                        "piece_quantity": str(raw.get("piece_quantity") or raw.get("quantity") or raw.get("qty") or ""),
                        "source": str(raw.get("source") or "C区材料明细"),
                    }
                )
            if out:
                return out
        md = req.get("materials_detail_rows")
        if isinstance(md, list):
            out = []
            for raw in md:
                if isinstance(raw, dict) and raw.get("standard_name_code"):
                    out.append(
                        {
                            "type": str(raw.get("type") or ""),
                            "standard_name_code": str(raw.get("standard_name_code") or ""),
                            "calculation_size": str(raw.get("calculation_size") or raw.get("calc_size") or ""),
                            "remark": str(raw.get("remark") or ""),
                            "usage": str(raw.get("usage") or raw.get("total_usage") or raw.get("quoted_usage") or ""),
                            "quantity": str(raw.get("quantity") or raw.get("piece_quantity") or raw.get("qty") or ""),
                            "piece_part": str(raw.get("piece_part") or raw.get("part_name") or raw.get("usage_part") or ""),
                            "piece_size": str(raw.get("piece_size") or raw.get("size") or ""),
                            "piece_quantity": str(raw.get("piece_quantity") or raw.get("quantity") or raw.get("qty") or ""),
                            "source": str(raw.get("source") or "C区材料明细"),
                        }
                    )
            if out:
                return out
    return []


def _structure_blob(quote: dict[str, Any], material_rows: list[dict[str, str]]) -> str:
    parts: list[str] = []
    for key in ("structure_text_snapshot", "structure_text", "structure_description"):
        val = str(quote.get(key) or "").strip()
        if val:
            parts.append(val)
    for row in material_rows:
        remark = str(row.get("remark") or "").strip()
        if remark and remark not in {"无", "-", "—"}:
            parts.append(remark)
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return "\n".join(out)


def _display_missing(value: object) -> bool:
    text = str(value or "").strip()
    return not text or text in {"无", "-", "—"}


def _material_display_name_key(name: str) -> str:
    text = str(name or "").strip().lower()
    return re.sub(r"\s+", "", text)


def _material_display_size_key(size: str) -> str:
    return ""


def _unique_texts(values: list[object]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        text = str(raw or "").strip()
        if _display_missing(text) or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


_USAGE_TEXT_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([^\d\s]+)\s*$")


def _sum_usage_texts(values: list[object]) -> str:
    totals: dict[str, float] = {}
    order: list[str] = []
    for raw in values:
        text = str(raw or "").strip()
        if _display_missing(text):
            continue
        match = _USAGE_TEXT_RE.match(text)
        if not match:
            continue
        unit = match.group(2)
        if unit not in totals:
            order.append(unit)
            totals[unit] = 0.0
        totals[unit] += float(match.group(1))
    if len(order) != 1:
        return ""
    unit = order[0]
    total = totals[unit]
    return f"{_fmt_dim(round(total, 4))}{unit}"


def _quote_item_pricing_lookup(quote: dict[str, Any]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for source_key in ("items", "detail_rows"):
        rows = quote.get(source_key)
        if not isinstance(rows, list):
            continue
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or raw.get("standard_name_code") or "").strip()
            if _display_missing(name):
                continue
            key = _material_display_name_key(name)
            if key in lookup:
                continue
            unit_price = str(raw.get("unit_price") or "").strip()
            usage = str(raw.get("usage") or raw.get("total_usage") or "").strip()
            amount = raw.get("amount")
            if _display_missing(unit_price) and _display_missing(usage) and amount in (None, ""):
                continue
            lookup[key] = {
                "unit_price": unit_price,
                "usage": usage,
                "amount": amount,
                "spec": str(raw.get("spec") or raw.get("calculation_size") or "").strip(),
            }
    return lookup


def _row_part_label(row: dict[str, Any], summary: dict[str, Any] | None) -> str:
    direct = str(row.get("piece_part") or row.get("part_name") or row.get("usage_part") or "").strip()
    if not _display_missing(direct):
        return direct
    remark = str(row.get("remark") or "").strip()
    if remark and remark not in {"无", "-", "—"}:
        return re.split(r"[，,；;\n/]+", remark, maxsplit=1)[0].strip() or remark
    if summary and isinstance(summary.get("pending_parts"), list) and summary["pending_parts"]:
        return str(summary["pending_parts"][0])
    if summary and isinstance(summary.get("covered_parts"), list) and summary["covered_parts"]:
        return str(summary["covered_parts"][0])
    return ""


def _quantity_from_detail_row(row: dict[str, Any], *, default: int = 1) -> int:
    for key in ("quantity", "piece_quantity", "usage", "piece_part", "piece_size"):
        text = str(row.get(key) or "")
        direct = re.search(r"数量\s*(\d+)", text)
        if direct:
            return max(1, int(direct.group(1)))
        qty = _parse_count_quantity(text, default=0)
        if qty > 0:
            return qty
    return default


def _non_area_quantity_display(rows: list[dict[str, Any]], summaries: list[dict[str, Any]]) -> tuple[str, int | None]:
    zipper_count = 0
    puller_count = 0
    other_count = 0
    for row in rows:
        blob = " ".join(
            str(row.get(key) or "")
            for key in ("standard_name_code", "standard_name", "name", "piece_part", "remark", "type")
        )
        qty = _quantity_from_detail_row(row)
        if re.search(r"拉头|slider", blob, re.I):
            puller_count += qty
        elif re.search(r"拉链|zipper|zip", blob, re.I):
            zipper_count += qty
        elif re.search(r"扣|五金|织带|绳|魔术贴|辅料|配件", blob, re.I):
            other_count += qty

    if zipper_count or puller_count or other_count:
        parts: list[str] = []
        if zipper_count:
            parts.append(f"{zipper_count}条")
        if puller_count:
            parts.append(f"{puller_count}个")
        if other_count:
            parts.append(f"{other_count}个")
        return "、".join(parts), zipper_count + puller_count + other_count

    for summary in summaries:
        if not isinstance(summary, dict):
            continue
        ms = summary.get("measure_summary")
        if not isinstance(ms, dict):
            continue
        qty = ms.get("quantity")
        try:
            qty_num = int(float(qty))
        except (TypeError, ValueError):
            continue
        if qty_num <= 0:
            continue
        unit = str(ms.get("measure_unit") or "").strip() or "个"
        return f"{qty_num}{unit}", qty_num
    return "", None


def _merge_summary_for_display(
    *,
    group_id: str,
    name: str,
    mat_type: str,
    size_text: str,
    summaries: list[dict[str, Any]],
    parts: list[str],
    usage_text: str,
    source: str,
    rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    pieces: list[dict[str, Any]] = []
    review_hints: list[str] = []
    covered: list[str] = []
    pending: list[str] = []
    excluded: list[str] = []
    total_cm2 = 0.0
    total_seen = False
    is_area = False
    for summary in summaries:
        if not isinstance(summary, dict):
            continue
        is_area = is_area or bool(summary.get("is_area_measurable") or summary.get("is_measurable"))
        pieces.extend([_finalize_piece(dict(p)) for p in summary.get("pieces") or [] if isinstance(p, dict)])
        review_hints.extend(str(x) for x in summary.get("review_hints") or [] if str(x).strip())
        covered.extend(str(x) for x in summary.get("covered_parts") or [] if str(x).strip())
        pending.extend(str(x) for x in summary.get("pending_parts") or [] if str(x).strip())
        excluded.extend(str(x) for x in summary.get("excluded_parts") or [] if str(x).strip())
        if summary.get("total_area_cm2") is not None:
            total_seen = True
            total_cm2 += float(summary.get("total_area_cm2") or 0)
    explicit_group_pieces = _explicit_pieces_from_group_rows(rows or [])
    if explicit_group_pieces:
        pieces = []
        existing: set[tuple[str, str, str]] = set()
        for piece in explicit_group_pieces:
            key = (
                str(piece.get("piece") or ""),
                str(piece.get("unit_area_cm2") or ""),
                str(piece.get("formula_key") or ""),
            )
            if key in existing:
                continue
            pieces.append(piece)
            covered.append(str(piece.get("piece") or ""))
            existing.add(key)
        total_cm2 = _total_area(pieces)
        total_seen = total_cm2 > 0
        pending = []
    pieces = _dedupe_merge_pieces(pieces)
    if is_area:
        total_cm2 = _total_area(pieces)
        total_seen = total_cm2 > 0
    total_cm2_out = round(total_cm2, 2) if total_seen and total_cm2 > 0 else None
    total_m2 = round(total_cm2_out / 10_000.0, 4) if total_cm2_out else None
    pending_parts = _unique_texts(pending) or _pending_part_labels(pieces)
    covered_parts = _unique_texts(covered) or _counted_covered_parts(pieces)
    review_hints_out = _unique_texts(review_hints)
    if pending_parts and not any("待" in h or "缺少" in h for h in review_hints_out):
        review_hints_out.append("组内存在待复核部位")
    display_summary = _build_display_summary(
        mat_type=mat_type,
        name=name,
        calc_size_text=size_text,
        structure_size_text="",
        total_m2=total_m2,
        loss=_loss_suggestions_m2(total_m2) if total_m2 else {},
        covered_parts=covered_parts,
        pending_parts=pending_parts,
        size_conflict=len(_unique_texts([s.get("calc_size_text") for s in summaries if isinstance(s, dict)])) > 1,
        review_hints=review_hints_out,
    )
    summary_text = f"{name}：覆盖{ '、'.join(parts) if parts else '多个部位' }。"
    if usage_text:
        summary_text += f" 汇总用量 {usage_text}。"
    return {
        "material_id": group_id,
        "material_name": name,
        "material_code": name,
        "material_type": mat_type,
        "source": source or "C区材料明细",
        "calc_size_text": size_text or "—",
        "structure_size_text": "—",
        "size_conflict": bool(display_summary.get("size_conflict")),
        "covered_parts": covered_parts,
        "excluded_parts": _unique_texts(excluded),
        "summary_text": summary_text,
        "total_area_cm2": total_cm2_out,
        "total_area_m2": total_m2,
        "loss_suggestions_m2": _loss_suggestions_m2(total_m2) if total_m2 else {},
        "review_hints": review_hints_out,
        "source_level": "display_group",
        "is_measurable": is_area,
        "is_area_measurable": is_area,
        "pieces": pieces,
        "measure_summary": None,
        "pending_parts": pending_parts,
        "display_summary": display_summary,
        "unmapped_notes": "",
        "kind": "display_group",
        "grouped_summary_ids": [str(s.get("material_id") or "") for s in summaries if isinstance(s, dict)],
    }


def _piece_count_display_from_pieces(
    pieces: list[dict[str, Any]],
    pending_parts: list[object] | None = None,
) -> tuple[str, float | None]:
    total = 0.0
    has_known = False
    pending_labels = set(_unique_texts(list(pending_parts or [])))
    for piece in pieces:
        if not isinstance(piece, dict):
            continue
        if piece.get("status") == "pending":
            label = str(piece.get("piece") or "").strip()
            pending_labels.add(label or f"pending_{len(pending_labels) + 1}")
            continue
        qty = piece.get("qty")
        try:
            qty_num = float(qty)
        except (TypeError, ValueError):
            continue
        if qty_num > 0:
            has_known = True
            total += qty_num
    if has_known:
        qty_text = _fmt_piece_qty_display(total)
        pending_count = len(pending_labels)
        if pending_count:
            return f"已识别{qty_text}片，{pending_count}项待核", total
        return qty_text, total
    return "缺少片数，待复核", None


def _summary_for_material(
    *,
    material_id: str,
    name: str,
    mat_type: str,
    source: str,
    calc_size_text: str,
    structure_size_text: str,
    size_conflict: bool,
    measure_kind: str,
    pieces: list[dict[str, Any]],
    covered_parts: list[str],
    excluded_parts: list[str],
    review_hints: list[str],
    measure_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    is_area_kind = measure_kind in {
        "main_fabric_area",
        "lining_area",
        "padding_area",
        "pu_piece_area",
        "mesh_area",
    }
    total_cm2 = _total_area(pieces) if is_area_kind else None
    total_m2 = round(total_cm2 / 10_000.0, 4) if total_cm2 and total_cm2 > 0 else None
    loss = _loss_suggestions_m2(total_m2) if total_m2 else {}

    if measure_kind == "count_with_length":
        ms = measure_summary or {}
        qty = ms.get("quantity", 1)
        if ms.get("pending_size"):
            summary_text = f"{name}：拉链尺寸待补充；按条计量；非㎡裁片，不计面积。"
        else:
            spec = ms.get("spec_text") or "—"
            summary_text = f"{name}：按结构推导拉链尺寸 {spec}，{qty}条；非㎡裁片，不计面积。"
    elif measure_kind == "length":
        summary_text = f"{name}：按长度计量；非㎡裁片，不计矩形展开面积。"
    elif measure_kind == "count":
        ms = measure_summary or {}
        if ms.get("is_badge_count"):
            qty = ms.get("quantity")
            if qty is not None:
                summary_text = f"{name}：按个计量，数量：{int(qty)}个；非㎡裁片，不计面积。"
            else:
                summary_text = f"{name}：按个计量，数量待补充；非㎡裁片，不计面积。"
        else:
            qty = ms.get("quantity", 1)
            unit = ms.get("measure_unit", "个")
            summary_text = f"{name}：按{unit}计量 {qty}{unit}；非㎡裁片，不计矩形展开面积。"
    elif measure_kind == "process":
        summary_text = f"{name}：按数量/工艺项；非㎡裁片，不计矩形展开面积。"
    elif measure_kind == "pending":
        summary_text = f"{name}：无法判断计量方式，待复核。"
    elif total_cm2 and total_cm2 > 0:
        with_loss = loss.get("3")
        if with_loss is None and total_m2:
            with_loss = round(float(total_m2) * 1.03, 4)
        summary_text = (
            f"{name}，按备注矩形展开，基础用量 {total_m2:.4f}㎡（展示 {_fmt_m2_display(total_m2)}）；"
            f"含3%损耗总用量 {_fmt_m2_display(with_loss)}㎡（仅展示）。"
        )
    else:
        summary_text = f"{name}：面积待估算 / 缺少覆盖范围，待补充。"

    source_level = "structure_text_parsed" if pieces else "unknown"
    if any(p.get("status") == "inferred" for p in pieces):
        source_level = "mixed"
    if not pieces and not measure_summary:
        source_level = "unknown"

    pieces = _finalize_pieces(pieces) if is_area_kind else pieces
    total_cm2 = _total_area(pieces) if is_area_kind else None
    total_m2 = round(total_cm2 / 10_000.0, 4) if total_cm2 and total_cm2 > 0 else None
    loss = _loss_suggestions_m2(total_m2) if total_m2 else {}
    pending_parts = _pending_part_labels(pieces) if is_area_kind else []
    display_summary = None
    if is_area_kind:
        display_summary = _build_display_summary(
            mat_type=mat_type,
            name=name,
            calc_size_text=calc_size_text,
            structure_size_text=structure_size_text,
            total_m2=total_m2,
            loss=loss,
            covered_parts=covered_parts,
            pending_parts=pending_parts,
            size_conflict=size_conflict,
            review_hints=review_hints,
        )

    return {
        "material_id": material_id,
        "material_name": name,
        "material_code": name,
        "material_type": mat_type,
        "material_measure_kind": measure_kind,
        "material_measure_kind_label": MEASURE_KIND_LABELS.get(measure_kind, measure_kind),
        "source": source or "C区材料明细",
        "calc_size_text": calc_size_text or "—",
        "structure_size_text": structure_size_text or "—",
        "size_conflict": size_conflict,
        "covered_parts": covered_parts,
        "excluded_parts": excluded_parts,
        "summary_text": summary_text,
        "total_area_cm2": total_cm2 if total_cm2 and total_cm2 > 0 else None,
        "total_area_m2": total_m2,
        "loss_suggestions_m2": loss if total_m2 else {},
        "review_hints": review_hints,
        "source_level": source_level,
        "is_measurable": is_area_kind,
        "is_area_measurable": is_area_kind,
        "pieces": pieces,
        "measure_summary": measure_summary,
        "pending_parts": pending_parts,
        "display_summary": display_summary,
        "unmapped_notes": "",
        # 兼容旧字段
        "kind": measure_kind,
    }


def build_material_piece_summaries(quote: dict[str, Any]) -> list[dict[str, Any]]:
    """按材料返回汇总+明细（只读，不参与计价）。"""
    if not isinstance(quote, dict):
        return []

    material_rows = _collect_material_rows(quote)
    struct_blob = _structure_blob(quote, material_rows)

    if not material_rows:
        detail_rows = quote.get("detail_rows") or quote.get("items") or []
        if isinstance(detail_rows, list):
            idx = 0
            for row in detail_rows:
                if not isinstance(row, dict):
                    continue
                name = str(row.get("name") or "").strip()
                if not name or not _is_fabric_material(name, name):
                    continue
                idx += 1
                material_rows.append(
                    {
                        "type": f"面料{idx}",
                        "standard_name_code": name,
                        "calculation_size": str(row.get("spec") or ""),
                        "remark": struct_blob[:2000] if idx == 1 else "",
                        "source": "BOM明细",
                    }
                )

    summaries: list[dict[str, Any]] = []

    zipper_row_indices: list[int] = []
    for i, row in enumerate(material_rows):
        name_probe = str(row.get("standard_name_code") or "").strip()
        mat_type_probe = str(row.get("type") or "").strip()
        remark_probe = str(row.get("remark") or "").strip()
        if _classify_material_measure_kind(name_probe, mat_type_probe, remark_probe) == "count_with_length":
            zipper_row_indices.append(i)
    total_zipper_rows = len(zipper_row_indices)

    for i, row in enumerate(material_rows):
        name = str(row.get("standard_name_code") or "").strip()
        if not name:
            continue
        mat_type = str(row.get("type") or "").strip()
        remark = str(row.get("remark") or "").strip()
        source = str(row.get("source") or "C区材料明细").strip()
        calc_size_text = str(row.get("calculation_size") or "").strip()
        if calc_size_text in {"无", "-", "—"}:
            calc_size_text = ""

        remark_blob = remark if remark and remark not in {"无", "-", "—"} else ""
        parsed_remark = _parse_material_remark(remark_blob)
        remark_dims = _parsed_to_structure_dims(parsed_remark) or _parse_structure_dims(remark_blob)
        row_structure_size_text = _fmt_lwh(*remark_dims) if remark_dims else ""

        calc_dims = _parse_calc_size_text(calc_size_text)
        conflict = _size_conflict(calc_dims, remark_dims)

        measure_kind = _classify_material_measure_kind(name, mat_type, remark)
        material_id = f"material_{i + 1}_{measure_kind}"

        review_hints: list[str] = []
        if conflict:
            review_hints.append(
                f"核算尺寸 {calc_size_text or '—'} 与备注结构尺寸 {row_structure_size_text or '—'} 不一致，待核"
            )
        if calc_size_text and not remark_dims and measure_kind in {
            "main_fabric_area",
            "lining_area",
            "padding_area",
        }:
            review_hints.append("备注说明未解析到结构主尺寸，仅保留核算尺寸供复核（不参与面积计算）")

        pieces: list[dict[str, Any]] = []
        covered: list[str] = []
        excluded: list[str] = ["织带", "拉链", "扣具"]
        measure_summary: dict[str, Any] | None = None

        if measure_kind == "main_fabric_area":
            excluded = ["底部 PU 隔离层", "K080 网", "织带/拉链/扣具"]
            if remark_blob:
                pieces, covered, piece_hints = _main_fabric_pieces_from_remark(
                    remark_blob,
                    main_name=name,
                    material_rows=material_rows,
                    struct_blob=struct_blob,
                )
                review_hints.extend(piece_hints)
            else:
                review_hints.append("缺少备注说明与结构尺寸，无法展开裁片面积")
            if not pieces:
                inferred = _inferred_piece_from_part_label(
                    _row_piece_text(row),
                    calc_size_text=calc_size_text,
                    source=source or "结构推断",
                )
                if inferred:
                    pieces.append(inferred)
                    covered.append(str(inferred.get("piece") or ""))
                    review_hints.append("表格未给明确片数，已按裁片/部位结构推断，需复核")
                else:
                    fallback_part = _row_piece_text(row)
                    if fallback_part:
                        pieces.append(_pending_piece(fallback_part, "缺少尺寸/片数", source=source or "C区材料明细"))
                        review_hints.append("表格裁片/部位无法推断尺寸或片数，待复核")
        elif measure_kind == "lining_area":
            pieces, covered, piece_hints = _lining_pieces_from_remark(remark_blob)
            review_hints.extend(piece_hints)
        elif measure_kind == "padding_area":
            pieces, covered, piece_hints = _padding_pieces_from_remark(remark_blob)
            review_hints.extend(piece_hints)
        elif measure_kind == "pu_piece_area":
            excluded = ["主料包身裁片"]
            pu_remark = remark_blob or struct_blob
            pieces, covered, piece_hints = _pu_pieces_from_remark(pu_remark, full_blob=struct_blob)
            review_hints.extend(piece_hints)
        elif measure_kind == "mesh_area":
            pieces, covered, piece_hints = _mesh_pieces_from_remark(remark_blob, full_blob=struct_blob)
            review_hints.extend(piece_hints)
        elif measure_kind == "count_with_length":
            zipper_row_index = (
                zipper_row_indices.index(i) if i in zipper_row_indices else 0
            )
            measure_summary, zipper_hints = _zipper_measure_summary_from_structure(
                name,
                remark_blob,
                struct_blob,
                zipper_row_index=zipper_row_index,
                total_zipper_rows=total_zipper_rows,
            )
            review_hints.extend(zipper_hints)
            excluded = []
        elif measure_kind == "length":
            measure_summary = _countable_measure_summary("米", remark_blob, calc_size_text)
            review_hints.append("非㎡裁片，按长度计量，不计矩形展开面积")
        elif measure_kind == "count":
            if _is_count_badge_material(name, mat_type, remark):
                measure_summary = _badge_measure_summary(name, remark_blob, calc_size_text)
                review_hints.append(f"需确认 {name}数量/位置")
            else:
                measure_summary = _count_measure_summary(remark_blob, calc_size_text)
                review_hints.append("非㎡裁片，按数量计量")
            excluded = []
        elif measure_kind == "process":
            review_hints.append("工艺/加工项，不计面积")
        else:
            if remark_blob:
                review_hints.append("无法判断材料计量类型，待复核")
            elif calc_size_text:
                review_hints.append("仅有核算尺寸，缺少备注覆盖范围，不计算面积")
            pieces.append(_pending_piece(name, "待复核"))

        _enrich_pending_piece_display(
            pieces,
            calc_size_text=calc_size_text,
            structure_size_text=row_structure_size_text,
        )
        counted_covered = _counted_covered_parts(pieces)

        summaries.append(
            _summary_for_material(
                material_id=material_id,
                name=name,
                mat_type=mat_type,
                source=source,
                calc_size_text=calc_size_text,
                structure_size_text=row_structure_size_text,
                size_conflict=conflict,
                measure_kind=measure_kind,
                pieces=pieces,
                covered_parts=counted_covered,
                excluded_parts=excluded,
                review_hints=review_hints,
                measure_summary=measure_summary,
            )
        )

    return summaries


def build_material_display_rows(quote: dict[str, Any]) -> list[dict[str, Any]]:
    """展示层聚合同名同规格材料；原始 BOM/detail rows 保持不变。"""
    if not isinstance(quote, dict):
        return []
    material_rows = _collect_material_rows(quote)
    if not material_rows:
        return []
    summaries = quote.get("material_piece_summaries")
    if not isinstance(summaries, list) or len(summaries) != len(material_rows):
        summaries = build_material_piece_summaries(quote)
    pricing_lookup = _quote_item_pricing_lookup(quote)

    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    order: list[tuple[str, str]] = []
    for idx, row in enumerate(material_rows):
        if not isinstance(row, dict):
            continue
        name = str(row.get("standard_name_code") or row.get("standard_name") or row.get("name") or "").strip()
        if _display_missing(name):
            continue
        size = str(row.get("calculation_size") or row.get("calc_size") or "").strip()
        if _display_missing(size):
            size = ""
        key = (_material_display_name_key(name), _material_display_size_key(size))
        summary = summaries[idx] if idx < len(summaries) and isinstance(summaries[idx], dict) else None
        if key not in buckets:
            order.append(key)
            buckets[key] = {
                "rows": [],
                "summaries": [],
                "name": name,
                "type": str(row.get("type") or ""),
                "sizes": [],
                "parts": [],
                "usages": [],
                "quantities": [],
                "sources": [],
            }
        bucket = buckets[key]
        bucket["rows"].append(row)
        if summary:
            bucket["summaries"].append(summary)
        bucket["sizes"].append(size)
        bucket["parts"].append(_row_part_label(row, summary))
        bucket["usages"].append(row.get("usage") or row.get("total_usage") or row.get("quoted_usage") or "")
        bucket["quantities"].append(row.get("quantity") or "")
        bucket["sources"].append(row.get("source") or "")

    out: list[dict[str, Any]] = []
    for display_idx, key in enumerate(order, start=1):
        bucket = buckets[key]
        rows = bucket["rows"]
        summaries_for_group = bucket["summaries"]
        sizes = _unique_texts(bucket["sizes"])
        parts = _unique_texts(bucket["parts"])
        usages = list(bucket["usages"])
        quantities = _unique_texts(bucket["quantities"])
        usage_text = _sum_usage_texts(usages) or (usages[0] if len(_unique_texts(usages)) == 1 else "")
        qty_text = quantities[0] if len(quantities) == 1 else usage_text
        size_text = sizes[0] if len(sizes) == 1 else ("、".join(sizes) if sizes else "无")
        source = "、".join(_unique_texts(bucket["sources"]))
        group_id = f"material_display_{display_idx}"
        pricing = pricing_lookup.get(str(key[0])) or {}
        quoted_usage = str(pricing.get("usage") or "").strip()
        quoted_unit_price = str(pricing.get("unit_price") or "").strip()
        quoted_amount = pricing.get("amount")
        if quoted_usage and not _display_missing(quoted_usage):
            usage_text = quoted_usage
        summary = _merge_summary_for_display(
            group_id=group_id,
            name=str(bucket["name"]),
            mat_type=str(bucket["type"]),
            size_text=size_text,
            summaries=summaries_for_group,
            parts=parts,
            usage_text=usage_text,
            source=source,
            rows=rows,
        )
        piece_count_display, pieces_count = _piece_count_display_from_pieces(
            [p for p in summary.get("pieces") or [] if isinstance(p, dict)],
            list(summary.get("pending_parts") or []),
        )
        if not summary.get("is_area_measurable"):
            non_area_qty, non_area_count = _non_area_quantity_display(rows, summaries_for_group)
            if non_area_qty:
                piece_count_display = non_area_qty
                pieces_count = non_area_count
        out.append(
            {
                "type": str(bucket["type"] or f"物料{display_idx}"),
                "material_name": str(bucket["name"]),
                "name": str(bucket["name"]),
                "standard_name_code": str(bucket["name"]),
                "calculation_size": size_text,
                "total_usage": usage_text,
                "usage": usage_text,
                "unit_price": quoted_unit_price if not _display_missing(quoted_unit_price) else "",
                "amount": quoted_amount,
                "quantity": piece_count_display,
                "quantity_display": piece_count_display,
                "piece_count_display": piece_count_display,
                "pieces_count": pieces_count,
                "parts": parts,
                "parts_text": "、".join(parts),
                "remark": summary.get("summary_text") or "",
                "source": source or "C区材料明细",
                "row_count": len(rows),
                "raw_rows": rows,
                "_material_id": group_id,
                "material_piece_summary": summary,
            }
        )
    return out


def build_material_area_overview(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    by_material: list[dict[str, Any]] = []
    total = 0.0
    for s in summaries:
        if not s.get("is_area_measurable"):
            continue
        area = s.get("total_area_cm2")
        if area is None:
            continue
        by_material.append({"name": s.get("material_name"), "area_cm2": area})
        total += float(area)

    total = round(total, 2)
    total_m2 = round(total / 10_000.0, 4)
    dedup = list(
        dict.fromkeys(
            w
            for s in summaries
            for w in (s.get("review_hints") or [])
            if "重复" in str(w)
        )
    )

    with_loss = round(total_m2 * 1.03, 2) if total_m2 > 0 else None
    proc_hint = f"{with_loss:.2f}" if with_loss else "—"

    return {
        "by_material": by_material,
        "total_before_dedup_cm2": total if total > 0 else None,
        "total_before_dedup_m2": total_m2 if total > 0 else None,
        "procurement_hint_m2": proc_hint,
        "dedup_warnings": dedup,
    }


def enrich_quote_material_piece_summaries(quote: dict[str, Any]) -> None:
    """写入 quote['material_piece_summaries'] 与 material_area_overview（只 enrich，不改计价）。"""
    if not isinstance(quote, dict):
        return
    summaries = build_material_piece_summaries(quote)
    quote["material_piece_summaries"] = summaries
    quote["material_area_overview"] = build_material_area_overview(summaries)
    quote["display_material_rows"] = build_material_display_rows(quote)
