from __future__ import annotations

import re
from typing import Any


EMPTY_TEXT = "无"
EXCEL_SOURCE = "excel"
C_MATERIAL_DETAIL_SOURCE = "c_material_detail"
STRUCTURE_SOURCE = "structure_description"


TEMPLATE_SECTIONS: tuple[dict[str, Any], ...] = (
    {
        "key": "A",
        "title": "A. 客户与报价信息",
        "fields": (
            ("customer_name", "客户名称", ("customer_name",)),
            ("sales_code", "业务员编号", ("sales_code", "salesperson_id", "sales_id")),
            ("country", "国家", ("country",)),
            ("city_ddp", "城市(DDP必填)", ("city", "city_ddp", "ddp_city")),
            ("incoterms", "Incoterms", ("incoterms",)),
            ("currency", "币种", ("currency",)),
            ("tax_13", "是否含税13%", ("include_tax", "tax_included", "tax_13")),
            ("margin_pct", "利润率%", ("margin_text", "gross_margin", "margin", "gross_margin_rate")),
            ("valid_days", "有效期(天)", ("valid_days", "validity_days")),
            ("delivery_requirement", "交期要求", ("delivery_requirement", "lead_time")),
            ("urgent_note", "加急说明", ("urgent_note", "rush_note")),
            ("quote_unit", "报价口径(单价单位)", ("quote_unit", "price_unit")),
            ("fx_usd_rmb", "汇率(USD-RMB)", ("fx_usd_rmb", "exchange_rate")),
            ("price_type", "价格类型(出厂/FOB)", ("price_type", "price_term")),
            ("fee_items", "费用包含项(多选)", ("fee_items", "included_fee_items")),
            ("fee_amount", "费用包含项金额(RMB/pc)", ("fee_amount", "included_fee_amount")),
            ("remark", "备注", ("remark", "note", "remarks")),
        ),
    },
    {
        "key": "B",
        "title": "B. 产品规格",
        "fields": (
            ("product_type", "产品类型", ("product_type", "type")),
            ("product_name_model", "产品名称/款号", ("product_name", "product_model", "model", "sku", "style_no", "name", "产品名称", "产品型号", "款号")),
            ("length_cm", "L(cm)", ("l_cm", "length_cm", "length", "L")),
            ("width_cm", "W(cm)", ("w_cm", "width_cm", "width", "W")),
            ("height_cm", "H(cm)", ("h_cm", "height_cm", "height", "H")),
            ("structure_complexity", "结构复杂度", ("structure_complexity",)),
            ("structure_description", "结构说明", ("structure_text", "structure_text_snapshot", "structure", "structure_description")),
            ("reference_images", "参考图片/链接", ("reference_images", "reference_links", "images", "links")),
        ),
    },
    {
        "key": "C",
        "title": "C. 材料与配件（标准名/编码）",
        "fields": (
            ("outer_material", "外料(标准名/编码)", ("outer_material", "outer_fabric", "shell_material")),
            ("outer_color", "外料颜色", ("outer_color", "shell_color")),
            ("lining_material", "里料(标准名/编码)", ("lining_material", "lining", "inner_material")),
            ("lining_color", "里料颜色", ("lining_color", "inner_color")),
            ("shaping", "定型", ("shaping", "forming")),
            ("waterproof_level", "防水等级", ("waterproof_level", "waterproof")),
            ("binding", "包边", ("binding", "edge_binding")),
            ("zipper", "拉链", ("zipper", "zipper_type", "拉链类型")),
            ("puller_type", "拉头类型", ("puller_type", "zipper_puller")),
            ("zipper_pull", "拉片", ("zipper_pull", "pull_tab")),
            ("buckle_level", "扣具等级", ("buckle_level",)),
            ("buckle_type", "扣具类型", ("buckle_type", "buckle")),
            ("top_binding_reinforcement", "顶部包边/口圈加固", ("top_binding_reinforcement", "top_binding")),
            ("handle_webbing", "手提织带", ("handle_webbing", "webbing_type", "strap_type")),
            ("handle_reinforcement", "手提加固", ("handle_reinforcement",)),
            ("bottom_reinforcement", "底部加固片", ("bottom_reinforcement", "bottom_patch")),
        ),
    },
    {
        "key": "D",
        "title": "D. 工艺（多选用；分隔）",
        "fields": (
            ("logo_method", "LOGO方式(多选)", ("logo_method", "logo_type", "LOGO方式")),
            ("logo_content", "LOGO内容", ("logo_content", "logo")),
            ("key_process", "关键工艺(多选)", ("key_process", "process", "关键工艺")),
            ("special_process_note", "特殊工艺备注", ("special_process_note", "process_note")),
        ),
    },
    {
        "key": "E",
        "title": "E. 模具与开料成本（一次性费用，系统可按数量摊销）",
        "fields": (
            ("cutting_mold_required", "是否需要开料模/刀模", ("cutting_mold_required", "need_cutting_mold")),
            ("cutting_mold_fee", "开料模/刀模费用(RMB)", ("cutting_mold_fee", "cutting_mold_cost")),
            ("hardware_mold_required", "是否需要五金模具", ("hardware_mold_required", "need_hardware_mold")),
            ("hardware_mold_fee", "五金模具费用(RMB)", ("hardware_mold_fee", "hardware_mold_cost")),
            ("plastic_mold_required", "是否需要塑胶模具", ("plastic_mold_required", "need_plastic_mold")),
            ("plastic_mold_fee", "塑胶模具费用(RMB)", ("plastic_mold_fee", "plastic_mold_cost")),
            ("mold_share_method", "模具费分摊方式", ("mold_share_method", "mold_amortization_method")),
            ("mold_share_quantity", "模具费分摊数量", ("mold_share_quantity", "mold_amortization_quantity")),
        ),
    },
    {
        "key": "F",
        "title": "F. 数量阶梯",
        "fields": (
            ("quantity_1", "数量1", ("quantity_1", "qty1")),
            ("quantity_2", "数量2", ("quantity_2", "qty2")),
            ("quantity_3", "数量3", ("quantity_3", "qty3")),
        ),
    },
)


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "" if isinstance(value, float) and value != value else str(value)
    if isinstance(value, dict):
        for key in ("text", "display", "label", "value", "raw"):
            val = _clean_text(value.get(key))
            if val:
                return val
        parts = []
        for key, val in value.items():
            txt = _clean_text(val)
            if txt:
                parts.append(f"{key}:{txt}")
        return "；".join(parts)
    if isinstance(value, (list, tuple, set)):
        parts = [_clean_text(v) for v in value]
        return " / ".join(p for p in parts if p)
    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "undefined", "nan", "-", "—"}:
        return ""
    return text


def _is_missing_text(value: object) -> bool:
    text = _clean_text(value)
    return not text or text == EMPTY_TEXT


def _norm_key(text: object) -> str:
    raw = str(text or "").strip().lower()
    raw = re.sub(r"\s+", "", raw)
    raw = raw.replace("（", "(").replace("）", ")")
    raw = raw.replace("：", ":").replace("；", ";")
    return raw


def _label_lookup() -> dict[str, str]:
    out: dict[str, str] = {}
    for section in TEMPLATE_SECTIONS:
        for _key, label, aliases in section["fields"]:
            out[_norm_key(label)] = label
            for alias in aliases:
                out[_norm_key(alias)] = label
    return out


def _excel_source_blocks(quote: dict[str, Any], meta: dict[str, Any] | None) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for raw in (
        quote.get("requirement_fields"),
        quote.get("bom_requirement_fields"),
        quote.get("quote_sheet_fields"),
        quote.get("quote_sheet_meta"),
        quote.get("quote_params"),
        quote.get("sheet_metadata"),
        meta.get("requirement_fields") if isinstance(meta, dict) else None,
        meta.get("quote_params") if isinstance(meta, dict) else None,
    ):
        if isinstance(raw, dict):
            blocks.append(raw)
            for val in raw.values():
                if isinstance(val, dict):
                    blocks.append(val)
    return blocks


def _fallback_source_blocks(quote: dict[str, Any], meta: dict[str, Any] | None) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for raw in (
        quote.get("product"),
        quote,
        meta or {},
    ):
        if isinstance(raw, dict):
            blocks.append(raw)
            for val in raw.values():
                if isinstance(val, dict):
                    blocks.append(val)
    return blocks


def _first_value(blocks: list[dict[str, Any]], label: str, aliases: tuple[str, ...]) -> str:
    candidates = (label, *aliases)
    wanted = {_norm_key(c) for c in candidates if str(c or "").strip()}
    for block in blocks:
        direct_keys = [label, *aliases]
        for key in direct_keys:
            if key in block:
                text = _clean_text(block.get(key))
                if text:
                    return text
        for raw_key, raw_val in block.items():
            if _norm_key(raw_key) in wanted:
                text = _clean_text(raw_val)
                if text:
                    return text
    return EMPTY_TEXT


def _extract_structure_text(quote: dict[str, Any], meta: dict[str, Any] | None) -> str:
    for raw in (
        quote.get("structure_text"),
        quote.get("structure_text_snapshot"),
        quote.get("structure_description"),
        meta.get("structure_text") if isinstance(meta, dict) else None,
        meta.get("structure_text_snapshot") if isinstance(meta, dict) else None,
    ):
        text = _clean_text(raw)
        if text:
            return text
    return ""


def _infer_field_from_structure(field_key: str, structure_text: str) -> str:
    text = _clean_text(structure_text)
    if not text:
        return ""
    if field_key == "handle_webbing":
        patterns = (
            r"手提(?:为|是|用|采用)?\s*([^，,。；;\n]*?织带)",
            r"手提[^，,。；;\n]{0,8}?([0-9一二三四五六七八九十寸分]+[^，,。；;\n]*?织带)",
        )
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return _clean_text(match.group(1))
    return ""


def _normalize_detail_row(raw: dict[str, Any]) -> dict[str, str] | None:
    row = {
        "type": _clean_text(raw.get("type") or raw.get("类型")),
        "standard_name_code": _clean_text(
            raw.get("standard_name_code")
            or raw.get("standard_name")
            or raw.get("name_code")
            or raw.get("外料(标准名/编码)")
            or raw.get("标准名/编码")
            or raw.get("主材料/规格")
        ),
        "calculation_size": _clean_text(raw.get("calculation_size") or raw.get("对应核算尺寸") or raw.get("size")),
        "piece_part": _clean_text(raw.get("piece_part") or raw.get("部位/裁片") or raw.get("部位裁片")),
        "piece_size": _clean_text(raw.get("piece_size") or raw.get("裁片尺寸") or raw.get("尺寸")),
        "piece_quantity": _clean_text(raw.get("piece_quantity") or raw.get("数量")),
        "usage": _clean_text(raw.get("usage") or raw.get("total_usage") or raw.get("quoted_usage") or raw.get("用量") or raw.get("总用量")),
        "total_usage": _clean_text(raw.get("total_usage") or raw.get("usage") or raw.get("quoted_usage") or raw.get("总用量") or raw.get("用量")),
        "quantity": _clean_text(raw.get("quantity") or raw.get("piece_quantity") or raw.get("数量")),
        "remark": _clean_text(raw.get("remark") or raw.get("备注说明") or raw.get("备注") or raw.get("尺寸/数量/备注")),
        "pricing_section": _clean_text(raw.get("pricing_section")) or "C",
        "included_in_quote": _clean_text(raw.get("included_in_quote")) or "是",
        "source": _clean_text(raw.get("source")) or EXCEL_SOURCE,
    }
    if all(
        _is_missing_text(row[key])
        for key in ("type", "standard_name_code", "calculation_size", "piece_part", "piece_size", "piece_quantity", "remark")
    ):
        return None
    if _is_missing_text(row["standard_name_code"]):
        return None
    for key in ("type", "standard_name_code", "calculation_size", "piece_part", "piece_size", "piece_quantity", "usage", "total_usage", "quantity", "remark"):
        if _is_missing_text(row[key]):
            row[key] = EMPTY_TEXT
    return row


_REMARK_SEGMENT_SPLIT = re.compile(r"[\n/、;；]+")
_DETAIL_SEGMENT_SPLIT = re.compile(r"[\n;；]+")
_QUANTITY_SEGMENT_RE = re.compile(
    r"^(?:数量\s*)?\d+(?:\.\d+)?\s*(?:片/套|片|条|个|只|套|对|米|码|pcs?|PCS?)$"
)
_SIZE_SEGMENT_RE = re.compile(
    r"^(?:[长宽高厚深]\s*)?(?:约\s*)?\d+(?:\.\d+)?\s*(?:cm|CM|厘米|mm|MM|毫米)?"
    r"(?:\s*[*xX×]\s*\d+(?:\.\d+)?\s*(?:cm|CM|厘米|mm|MM|毫米)?){0,2}$"
)
_SIZE_POLLUTION_RE = re.compile(
    r"按实际尺寸填写|底宽|侧宽|按条计价|按个计价|备注|待补|待填写|参考|结构备注|面积表合计"
)
_ACCESSORY_MATERIAL_RE = re.compile(r".*(?:拉链|拉头|扣|织带|包边|绳|魔术贴|四合扣|磁扣|日字扣|方扣|插扣).*")


def _remark_segment_references_sibling_type(segment: str, sibling_types: set[str], *, own_type: str) -> bool:
    text = _clean_text(segment)
    if _is_missing_text(text):
        return True
    compact = re.sub(r"\s+", "", text)
    for typ in sibling_types:
        if not typ or typ == own_type:
            continue
        typ_compact = re.sub(r"\s+", "", typ)
        if compact == typ_compact:
            return True
        for prefix in ("内部为", "内部", "内为", "内含", "对应", "配套"):
            if compact == f"{prefix}{typ_compact}":
                return True
        if re.fullmatch(rf"(?:内部为?|内为|内含|对应|配套)\s*{re.escape(typ)}", text):
            return True
    return False


def _clean_detail_row_remarks(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    if not rows:
        return rows
    sibling_types = {
        typ
        for row in rows
        if not _is_missing_text(typ := _clean_text(row.get("type")))
    }
    cleaned: list[dict[str, str]] = []
    for row in rows:
        next_row = dict(row)
        remark = _clean_text(row.get("remark"))
        if _is_missing_text(remark):
            cleaned.append(next_row)
            continue
        own_type = _clean_text(row.get("type"))
        kept: list[str] = []
        for segment in _REMARK_SEGMENT_SPLIT.split(remark):
            seg = segment.strip()
            if not seg or _remark_segment_references_sibling_type(seg, sibling_types, own_type=own_type):
                continue
            kept.append(seg)
        next_row["remark"] = " / ".join(kept) if kept else EMPTY_TEXT
        cleaned.append(next_row)
    return cleaned


def _is_quantity_segment(text: str) -> bool:
    compact = _clean_text(text).replace(" ", "")
    if not compact:
        return False
    return bool(_QUANTITY_SEGMENT_RE.match(compact))


def _is_size_segment(text: str) -> bool:
    segment = _clean_text(text)
    if not segment or _SIZE_POLLUTION_RE.search(segment):
        return False
    compact = segment.replace(" ", "")
    return bool(_SIZE_SEGMENT_RE.match(compact))


def _normalize_quantity_segment(text: str) -> str:
    segment = _clean_text(text).replace(" ", "")
    if not segment:
        return ""
    if segment.startswith("数量"):
        return segment
    if re.match(r"^\d", segment):
        return f"数量{segment}"
    return segment


def _split_size_quantity_remark(text: str) -> dict[str, str]:
    raw = _clean_text(text).replace("：", "；").replace(":", "；")
    if not raw:
        return {"piece_size": "", "piece_quantity": "", "remark": ""}
    size_parts: list[str] = []
    qty_parts: list[str] = []
    remark_parts: list[str] = []
    for part in _DETAIL_SEGMENT_SPLIT.split(raw):
        segment = _clean_text(part)
        if not segment:
            continue
        if _is_quantity_segment(segment):
            qty = _normalize_quantity_segment(segment)
            if qty and qty not in qty_parts:
                qty_parts.append(qty)
        elif _is_size_segment(segment):
            if segment not in size_parts:
                size_parts.append(segment)
        else:
            if segment not in remark_parts:
                remark_parts.append(segment)
    return {
        "piece_size": " / ".join(size_parts),
        "piece_quantity": " / ".join(qty_parts),
        "remark": " / ".join(remark_parts),
    }


def _extract_accessory_material_name(segment: str) -> str:
    text = _clean_text(segment)
    if not text:
        return ""
    if _ACCESSORY_MATERIAL_RE.match(text) and not _is_quantity_segment(text) and not _is_size_segment(text):
        return text
    return ""


def _resolve_horizontal_material_name(main_material: str, piece_part: str, detail_text: str) -> tuple[str, str]:
    material = _clean_text(main_material)
    detail = _clean_text(detail_text)
    if material != "多规格配件":
        return material, detail
    segments = [_clean_text(x) for x in _DETAIL_SEGMENT_SPLIT.split(detail) if _clean_text(x)]
    for segment in segments:
        accessory = _extract_accessory_material_name(segment)
        if accessory:
            kept = [seg for seg in segments if seg != segment]
            return accessory, "；".join(kept)
    return material, detail


def _materials_detail_rows(quote: dict[str, Any], meta: dict[str, Any] | None) -> list[dict[str, str]]:
    candidates = (
        quote.get("materials_detail_rows"),
        quote.get("bom_requirement_materials_detail_rows"),
        meta.get("materials_detail_rows") if isinstance(meta, dict) else None,
    )
    out: list[dict[str, str]] = []
    for raw_rows in candidates:
        if not isinstance(raw_rows, list):
            continue
        for raw in raw_rows:
            if not isinstance(raw, dict):
                continue
            row = _normalize_detail_row(raw)
            if row is not None:
                out.append(row)
        if out:
            return _clean_detail_row_remarks(out)
    return out


def _append_detail_value(values: list[str], value: object, *, dedupe: bool = True) -> None:
    text = _clean_text(value)
    if _is_missing_text(text):
        return
    if dedupe and text in values:
        return
    values.append(text)


def _detail_material_line_label(material_type: str, material_name: str) -> str:
    typ = _clean_text(material_type)
    name = _clean_text(material_name)
    if _is_missing_text(name):
        return ""
    if _is_missing_text(typ):
        return name
    return f"{typ}：{name}"


def _extract_accessory_product_name(remark: str) -> str:
    text = _clean_text(remark)
    if not text:
        return ""
    return re.split(r"[;；/／]", text, maxsplit=1)[0].strip()


def _is_zipper_piece_part(piece_part: str) -> bool:
    return bool(re.match(r"^拉链\d*$", _clean_text(piece_part)))


def _is_puller_piece_part(piece_part: str) -> bool:
    return bool(re.match(r"^拉头\d*$", _clean_text(piece_part)))


def _is_outer_fabric_material_type(material_type: str) -> bool:
    typ = _clean_text(material_type)
    if not typ:
        return False
    if "外料" in typ:
        return True
    if typ.startswith("面料"):
        return True
    return bool(re.match(r"^面料\d+", typ))


def _is_lining_material_type(material_type: str) -> bool:
    typ = _clean_text(material_type)
    return any(token in typ for token in ("里布", "内衬", "里料"))


def has_horizontal_c_material_detail_layout(detail_rows: list[dict[str, str]]) -> bool:
    if not isinstance(detail_rows, list) or not detail_rows:
        return False
    piece_rows = [
        row
        for row in detail_rows
        if isinstance(row, dict) and not _is_missing_text(row.get("piece_part"))
    ]
    return len(piece_rows) >= 2


def _material_detail_field_values(rows: list[dict[str, str]]) -> dict[str, str]:
    buckets: dict[str, list[str]] = {
        "outer_material": [],
        "lining_material": [],
        "zipper": [],
        "puller_type": [],
        "handle_webbing": [],
        "buckle_type": [],
        "binding": [],
        "bottom_reinforcement": [],
    }
    for row in rows:
        material_type = _clean_text(row.get("type"))
        material_name = _clean_text(row.get("standard_name_code"))
        piece_part = _clean_text(row.get("piece_part"))
        remark = _clean_text(row.get("remark"))
        if _is_missing_text(material_type) or _is_missing_text(material_name):
            continue
        accessory_name = material_name
        if _is_outer_fabric_material_type(material_type):
            _append_detail_value(buckets["outer_material"], material_name)
        elif _is_lining_material_type(material_type):
            _append_detail_value(buckets["lining_material"], material_name)
        elif _is_zipper_piece_part(piece_part):
            _append_detail_value(buckets["zipper"], accessory_name)
        elif _is_puller_piece_part(piece_part):
            _append_detail_value(buckets["puller_type"], accessory_name)
        elif "拉链" in material_type:
            _append_detail_value(buckets["zipper"], accessory_name or material_name)
        elif "拉头" in material_type:
            _append_detail_value(buckets["puller_type"], accessory_name or material_name)
        elif "织带" in material_type or piece_part.startswith("手提") or piece_part == "手提":
            _append_detail_value(buckets["handle_webbing"], accessory_name or material_name)
        elif "扣具" in material_type or "扣" in material_type:
            _append_detail_value(buckets["buckle_type"], accessory_name or material_name)
        elif "包边" in material_type:
            _append_detail_value(buckets["binding"], accessory_name or material_name)
        elif any(token in material_type for token in ("底部", "底片", "底板", "加固片", "PU料", "加强片")):
            _append_detail_value(buckets["bottom_reinforcement"], accessory_name or material_name)
        elif ("配件" in material_type or "辅料" in material_type) and _is_zipper_piece_part(piece_part):
            _append_detail_value(buckets["zipper"], accessory_name or remark)
        elif ("配件" in material_type or "辅料" in material_type) and _is_puller_piece_part(piece_part):
            _append_detail_value(buckets["puller_type"], accessory_name or remark)
        elif ("配件" in material_type or "辅料" in material_type) and (
            "扣" in piece_part or "扣" in remark
        ):
            _append_detail_value(buckets["buckle_type"], accessory_name or remark)
    out: dict[str, str] = {}
    for key, values in buckets.items():
        if not values:
            continue
        if key in {"outer_material", "lining_material"}:
            out[key] = "；".join(values)
        else:
            out[key] = " / ".join(values)
    return out


def build_admin_bom_requirement_view(
    quote: dict[str, Any] | None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    q = quote if isinstance(quote, dict) else {}
    excel_blocks = _excel_source_blocks(q, meta)
    fallback_blocks = _fallback_source_blocks(q, meta)
    structure_text = _extract_structure_text(q, meta)
    materials_detail_rows = _materials_detail_rows(q, meta)
    material_detail_values = _material_detail_field_values(materials_detail_rows)
    sections: list[dict[str, Any]] = []
    for section in TEMPLATE_SECTIONS:
        fields: list[dict[str, Any]] = []
        for key, label, aliases in section["fields"]:
            value = _first_value(excel_blocks, label, aliases)
            source = EXCEL_SOURCE if not _is_missing_text(value) else "empty"
            inferred = False
            if _is_missing_text(value):
                detail_value = material_detail_values.get(key, "")
                if detail_value:
                    value = detail_value
                    source = C_MATERIAL_DETAIL_SOURCE
            if _is_missing_text(value):
                inferred_value = _infer_field_from_structure(key, structure_text)
                if inferred_value:
                    value = inferred_value
                    source = STRUCTURE_SOURCE
                    inferred = True
            if _is_missing_text(value):
                fallback_value = _first_value(fallback_blocks, label, aliases)
                if not _is_missing_text(fallback_value):
                    value = fallback_value
                    source = "quote"
            if _is_missing_text(value):
                value = EMPTY_TEXT
                source = "empty"
            fields.append(
                {
                    "key": key,
                    "label": label,
                    "value": value,
                    "source": source,
                    "inferred": inferred,
                }
            )
        section_obj = {
            "key": str(section["key"]),
            "title": str(section["title"]),
            "fields": fields,
        }
        if str(section["key"]) == "C":
            section_obj["detail_rows"] = materials_detail_rows
        sections.append(section_obj)
    return {"empty_text": EMPTY_TEXT, "sections": sections}


def _is_section_row(row: list[str]) -> bool:
    first = next((str(c or "").strip() for c in row if str(c or "").strip()), "")
    return bool(re.match(r"^[A-Fa-f]\s*[.．、]", first))


def _header_map_for_row(row: list[str]) -> dict[int, str]:
    lookup = _label_lookup()
    out: dict[int, str] = {}
    for idx, cell in enumerate(row):
        label = lookup.get(_norm_key(cell))
        if label:
            out[idx] = label
    return out


DETAIL_HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "type": ("类型", "类别", "材料类型", "type"),
    "standard_name_code": (
        "外料(标准名/编码)",
        "标准名/编码",
        "标准名",
        "编码",
        "名称/编码",
        "材料名称",
        "主材料/规格",
        "主材料规格",
        "standard_name_code",
    ),
    "calculation_size": ("对应核算尺寸", "核算尺寸", "尺寸", "用量尺寸", "calculation_size"),
    "remark": ("备注说明", "备注", "说明", "remark"),
}

_HORIZONTAL_PART_HEADER = re.compile(r"^部位[/／]裁片\d*$")
_HORIZONTAL_SIZE_REMARK_HEADER = re.compile(r"^尺寸[/／]数量[/／]备注\d*$")
_HORIZONTAL_PART_HEADER_UTF8 = re.compile(r"^部位[/／]裁片(\d*)$")
_HORIZONTAL_SIZE_HEADER_UTF8 = re.compile(r"^尺寸(\d+)$")
_HORIZONTAL_QUANTITY_HEADER_UTF8 = re.compile(r"^数量(\d+)$")
_HORIZONTAL_SIZE_REMARK_HEADER_UTF8 = re.compile(r"^尺寸[/／]数量[/／]备注(\d*)$")
_PLACEHOLDER_DETAIL_VALUES = frozenset(
    {
        "按实际尺寸填写",
        "待填写",
        "待补充",
        "待定",
        "无",
    }
)


def _detail_header_map_for_row(row: list[str]) -> dict[int, str]:
    out: dict[int, str] = {}
    lookup = {
        _norm_key(alias): key
        for key, aliases in DETAIL_HEADER_ALIASES.items()
        for alias in aliases
    }
    for idx, cell in enumerate(row):
        key = lookup.get(_norm_key(cell))
        if key:
            out[idx] = key
    return out


def _row_has_horizontal_part_columns(row: list[str]) -> bool:
    for cell in row:
        text = _clean_text(cell)
        if not text:
            continue
        if _HORIZONTAL_PART_HEADER.match(text):
            return True
    return False


def _is_horizontal_c_material_detail_header(row: list[str]) -> bool:
    keys = set(_detail_header_map_for_row(row).values())
    if "type" not in keys or "standard_name_code" not in keys:
        return False
    return "calculation_size" in keys or _row_has_horizontal_part_columns(row)


def _is_material_detail_header(row: list[str]) -> bool:
    if _is_horizontal_c_material_detail_header(row):
        return True
    keys = set(_detail_header_map_for_row(row).values())
    return "type" in keys and "standard_name_code" in keys and (
        "calculation_size" in keys or "remark" in keys
    )


def _is_probable_detail_row(row: list[str], header: dict[int, str]) -> bool:
    values = {field: _clean_text(row[col] if col < len(row) else "") for col, field in header.items()}
    return bool(values.get("type") or values.get("standard_name_code") or values.get("calculation_size") or values.get("remark"))


def _detail_pair_is_placeholder(part: str, remark: str) -> bool:
    part_text = _clean_text(part)
    remark_text = _clean_text(remark)
    if not part_text and not remark_text:
        return True
    if part_text in _PLACEHOLDER_DETAIL_VALUES and remark_text in _PLACEHOLDER_DETAIL_VALUES:
        return True
    if part_text in _PLACEHOLDER_DETAIL_VALUES and not remark_text:
        return True
    if remark_text in _PLACEHOLDER_DETAIL_VALUES and not part_text:
        return True
    return False


def _horizontal_detail_groups(header_row: list[str] | None) -> list[dict[str, int | str]]:
    if not isinstance(header_row, list):
        return []
    parts: dict[str, int] = {}
    sizes: dict[str, int] = {}
    quantities: dict[str, int] = {}
    combined: dict[str, int] = {}
    for idx, raw in enumerate(header_row):
        text = _clean_text(raw).replace(" ", "")
        if not text:
            continue
        m = _HORIZONTAL_PART_HEADER_UTF8.match(text)
        if m:
            parts[m.group(1) or str(len(parts) + 1)] = idx
            continue
        m = _HORIZONTAL_SIZE_REMARK_HEADER_UTF8.match(text)
        if m:
            combined[m.group(1) or str(len(combined) + 1)] = idx
            continue
        m = _HORIZONTAL_SIZE_HEADER_UTF8.match(text)
        if m:
            sizes[m.group(1)] = idx
            continue
        m = _HORIZONTAL_QUANTITY_HEADER_UTF8.match(text)
        if m:
            quantities[m.group(1)] = idx
    groups: list[dict[str, int | str]] = []
    for suffix, part_col in sorted(parts.items(), key=lambda item: item[1]):
        if suffix in combined:
            groups.append({"kind": "combined", "part_col": part_col, "detail_col": combined[suffix]})
        elif suffix in sizes or suffix in quantities:
            groups.append(
                {
                    "kind": "triplet",
                    "part_col": part_col,
                    "size_col": sizes.get(suffix, -1),
                    "quantity_col": quantities.get(suffix, -1),
                }
            )
    return groups


def _expand_horizontal_c_detail_row(row: list[str], header_row: list[str] | None = None) -> list[dict[str, str]]:
    material_type = _clean_text(row[0] if len(row) > 0 else "")
    main_material = _clean_text(row[1] if len(row) > 1 else "")
    calc_size = _clean_text(row[2] if len(row) > 2 else "")
    if _is_missing_text(main_material):
        return []
    expanded: list[dict[str, str]] = []
    pair_found = False
    groups = _horizontal_detail_groups(header_row)
    if groups:
        iterable: list[tuple[str, str, str]] = []
        for group in groups:
            part_col = int(group.get("part_col", -1))
            part = _clean_text(row[part_col] if 0 <= part_col < len(row) else "")
            if group.get("kind") == "triplet":
                size_col = int(group.get("size_col", -1))
                quantity_col = int(group.get("quantity_col", -1))
                size = _clean_text(row[size_col] if 0 <= size_col < len(row) else "")
                qty = _clean_text(row[quantity_col] if 0 <= quantity_col < len(row) else "")
                detail_text = size
            else:
                detail_col = int(group.get("detail_col", -1))
                detail_text = _clean_text(row[detail_col] if 0 <= detail_col < len(row) else "")
                qty = ""
            iterable.append((part, detail_text, qty))
    else:
        iterable = []
        col = 3
        while col + 1 < len(row):
            iterable.append((_clean_text(row[col]), _clean_text(row[col + 1]), ""))
            col += 2
    for part, remark, qty_text in iterable:
        if _detail_pair_is_placeholder(part, remark):
            continue
        pair_found = True
        resolved_material, detail_text = _resolve_horizontal_material_name(main_material, part, remark)
        split_detail = _split_size_quantity_remark(detail_text)
        if qty_text and not split_detail["piece_quantity"]:
            split_detail["piece_quantity"] = _normalize_quantity_segment(qty_text)
        normalized = _normalize_detail_row(
            {
                "type": material_type,
                "standard_name_code": resolved_material,
                "calculation_size": calc_size,
                "piece_part": part,
                "piece_size": split_detail["piece_size"],
                "piece_quantity": split_detail["piece_quantity"],
                "remark": split_detail["remark"],
                "pricing_section": "C",
                "included_in_quote": "是",
            }
        )
        if normalized is not None:
            expanded.append(normalized)
    if not pair_found:
        normalized = _normalize_detail_row(
            {
                "type": material_type,
                "standard_name_code": main_material,
                "calculation_size": calc_size,
                "quantity": _clean_text(row[3] if len(row) > 3 else ""),
                "pricing_section": "C",
                "included_in_quote": "是",
            }
        )
        if normalized is not None:
            expanded.append(normalized)
    return expanded


def extract_material_detail_rows_from_rows(rows: list[list[str]]) -> list[dict[str, str]]:
    if not isinstance(rows, list):
        return []
    out: list[dict[str, str]] = []
    in_c_section = False
    active_header: dict[int, str] | None = None
    active_horizontal_header: list[str] | None = None
    horizontal_layout = False
    for raw_row in rows:
        row = raw_row if isinstance(raw_row, list) else []
        if _is_section_row(row):
            first = next((str(c or "").strip() for c in row if str(c or "").strip()), "")
            in_c_section = bool(re.match(r"^[Cc]\s*[.．、]", first))
            active_header = None
            active_horizontal_header = None
            horizontal_layout = False
            continue
        if not in_c_section:
            continue
        if _is_material_detail_header(row):
            active_header = _detail_header_map_for_row(row)
            horizontal_layout = _is_horizontal_c_material_detail_header(row)
            active_horizontal_header = row if horizontal_layout else None
            continue
        if active_header is None:
            continue
        if not any(_clean_text(cell) for cell in row):
            continue
        if _section_for_header(set(_header_map_for_row(row).values())) is not None:
            active_header = None
            active_horizontal_header = None
            horizontal_layout = False
            continue
        if horizontal_layout:
            out.extend(_expand_horizontal_c_detail_row(row, active_horizontal_header))
            continue
        if not _is_probable_detail_row(row, active_header):
            continue
        raw: dict[str, str] = {}
        for col_idx, field in active_header.items():
            raw[field] = _clean_text(row[col_idx] if col_idx < len(row) else "")
        normalized = _normalize_detail_row(raw)
        if normalized is not None:
            out.append(normalized)
    return _clean_detail_row_remarks(out)


def enrich_requirement_fields_from_material_details(
    requirement_fields: dict[str, str],
    detail_rows: list[dict[str, str]],
) -> dict[str, str]:
    if not isinstance(requirement_fields, dict):
        return {}
    detail_values = _material_detail_field_values(detail_rows)
    label_by_key: dict[str, str] = {}
    for section in TEMPLATE_SECTIONS:
        if str(section.get("key")) != "C":
            continue
        for key, label, _aliases in section["fields"]:
            label_by_key[str(key)] = str(label)
    out = dict(requirement_fields)
    for field_key, value in detail_values.items():
        label = label_by_key.get(field_key)
        if not label:
            continue
        if _is_missing_text(out.get(label)):
            out[label] = value
        elif field_key in {"outer_material", "lining_material", "zipper", "puller_type"} and not _is_missing_text(value):
            out[label] = value
    return out


def _section_for_header(labels: set[str]) -> dict[str, Any] | None:
    best: tuple[int, dict[str, Any] | None] = (0, None)
    for section in TEMPLATE_SECTIONS:
        section_labels = {label for _key, label, _aliases in section["fields"]}
        score = len(labels & section_labels)
        if score > best[0]:
            best = (score, section)
    return best[1] if best[0] >= 2 else None


def _next_nonempty_rows(rows: list[list[str]], start: int) -> list[list[str]]:
    out: list[list[str]] = []
    for row in rows[start:]:
        if _is_section_row(row):
            break
        if _is_material_detail_header(row):
            break
        if _section_for_header(set(_header_map_for_row(row).values())) is not None:
            break
        if not any(str(c or "").strip() for c in row):
            continue
        out.append(row)
    return out


def _merge_field_value(existing: str, incoming: str) -> str:
    val = _clean_text(incoming)
    if not val:
        return existing
    if not existing or existing == EMPTY_TEXT:
        return val
    parts = [p.strip() for p in existing.split(" / ") if p.strip()]
    if val in parts:
        return existing
    return f"{existing} / {val}"


def extract_requirement_fields_from_rows(rows: list[list[str]]) -> dict[str, str]:
    result = {
        label: EMPTY_TEXT
        for section in TEMPLATE_SECTIONS
        for _key, label, _aliases in section["fields"]
    }
    if not isinstance(rows, list):
        return result
    for idx, row in enumerate(rows):
        header = _header_map_for_row(row if isinstance(row, list) else [])
        if not header:
            continue
        section = _section_for_header(set(header.values()))
        if section is None:
            continue
        section_key = str(section["key"])
        value_rows = _next_nonempty_rows(rows, idx + 1)
        if section_key != "C":
            value_rows = value_rows[:1]
        for value_row in value_rows:
            for col_idx, label in header.items():
                raw = value_row[col_idx] if col_idx < len(value_row) else ""
                result[label] = _merge_field_value(result[label], raw)
    return result
