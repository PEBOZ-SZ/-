from __future__ import annotations

import json
import os
import re
from typing import Any


def _response(
    intent: str,
    patches: list[dict[str, Any]] | None = None,
    message: str = "",
    recalc: bool = False,
) -> dict[str, Any]:
    return {
        "intent": intent,
        "patches": patches or [],
        "assistant_message": message,
        "needs_recalculate": bool(recalc),
    }


def _clean_material_name(text: str) -> str:
    cleaned = str(text or "").strip()
    cleaned = re.sub(r"^(请|帮我|把|将|和|、|，|,|\s)+", "", cleaned)
    cleaned = re.sub(
        r"(都|全部|一起|正式|BOM|bom|报价|材料|物料|单价|价格|用量)$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned.strip(" ，,。、；;：:")


def _split_materials(text: str) -> list[str]:
    return [
        name
        for name in (_clean_material_name(part) for part in re.split(r"和|、|，|,|及", text))
        if name
    ]


def _dedupe_patches(patches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for patch in patches:
        key = repr(sorted(patch.items()))
        if key in seen:
            continue
        seen.add(key)
        out.append(patch)
    return out


def parse_quote_draft_patches_by_rules(user_text: str, draft: dict | None = None) -> dict[str, Any]:
    _ = draft
    text = str(user_text or "").strip()
    if not text:
        return _response(
            "clarify",
            message="请补充要修改的报价字段，例如“数量改300”或“PU料按6.5”。",
        )

    compact = re.sub(r"\s+", "", text)
    if re.search(r"(确认保存|保存提交审批|提交审批|确认提交|保存报价)", compact):
        return _response("confirm_save", message="收到，我会先检查草稿风险，再提交正式保存。")
    if re.search(r"(重新计算|重算|再算一次|刷新报价)", compact):
        return _response("recalculate", message="收到，按当前草稿重新计算。", recalc=True)

    patches: list[dict[str, Any]] = []

    multi_qty_match = re.search(r"(?:数量|件数)(?:改|改成|调整为|设为|=|：|:)?(\d+)(?:和|、|,|，)(\d+)(?:两档|档|个档|件)?", compact)
    if multi_qty_match:
        patches.append(
            {
                "op": "set_quantities",
                "quantities": [int(multi_qty_match.group(1)), int(multi_qty_match.group(2))],
            }
        )

    for match in re.finditer(r"(?:数量|件数)(?:改|改成|调整为|设为|=|：|:)?(\d+)", compact):
        if not any(p.get("op") == "set_quantities" for p in patches):
            patches.append({"op": "set_quantities", "quantities": [int(match.group(1))]})
    if not any(p.get("op") == "set_quantities" for p in patches):
        m_qty = re.fullmatch(r"(\d+)件", compact)
        if m_qty:
            patches.append({"op": "set_quantities", "quantities": [int(m_qty.group(1))]})

    for match in re.finditer(
        r"(?:毛利|利润率|毛利率)(?:改|改成|调整为|设为|按|=|：|:)?(\d+(?:\.\d+)?)(%|个点|点)?",
        compact,
    ):
        value = float(match.group(1))
        patches.append(
            {
                "op": "set_margin",
                "gross_margin_rate": value / 100.0 if value > 1 or match.group(2) else value,
            }
        )

    for match in re.finditer(
        r"加工费(?:改|改成|调整为|设为|按|=|：|:)?(\d+(?:\.\d+)?)(?:元)?",
        compact,
    ):
        patches.append({"op": "set_processing_fee", "processing_fee": float(match.group(1))})

    for match in re.finditer(
        r"([^，。；;\s]+?)(?:每个)?用量(?:按|改|改成|调整为|设为|=|：|:)?(\d+(?:\.\d+)?)(?:平方|平米|㎡|米|m|码|个|条)?",
        compact,
    ):
        material = _clean_material_name(match.group(1))
        if material and material not in {"数量", "毛利", "加工费"}:
            patches.append({"op": "set_material_usage", "material": material, "usage": float(match.group(2))})

    if re.search(r"(不含税|不要含税|无需含税)", compact):
        patches.append({"op": "set_include_tax", "include_tax": False})
    elif re.search(r"(要含税|含税|算税|带税)", compact):
        patches.append({"op": "set_include_tax", "include_tax": True})

    if re.search(r"(不含FOB|不要FOB|无需FOB|EXW就行|EXW即可|只要EXW)", compact, flags=re.IGNORECASE):
        patches.append({"op": "set_include_fob", "include_fob": False})
    elif re.search(r"(含FOB|FOB也算进去|FOB算进去|FOB也要|加FOB)", compact, flags=re.IGNORECASE):
        patches.append({"op": "set_include_fob", "include_fob": True})

    for match in re.finditer(
        r"([^，。；;\s]+?)(?:按(?:上次那个|上次|那个)?|单价|价格)(\d+(?:\.\d+)?)(?:元)?",
        compact,
    ):
        if "用量" in match.group(0) or "毛利" in match.group(0) or "毛利率" in match.group(0) or "利润率" in match.group(0):
            continue
        material = _clean_material_name(match.group(1))
        if material and material not in {"数量", "毛利", "加工费"} and "用量" not in material:
            patches.append({"op": "set_material_price", "material": material, "unit_price": float(match.group(2))})

    for match in re.finditer(r"([^。；;]+?)(?:都)?加入正式?BOM", compact, flags=re.IGNORECASE):
        for material in _split_materials(match.group(1)):
            patches.append({"op": "set_material_included", "material": material, "included": True})

    for match in re.finditer(r"([^。；;，,]+?)(?:不参与报价|不计价|移出正式?BOM)", compact, flags=re.IGNORECASE):
        material = _clean_material_name(match.group(1))
        if material:
            patches.append({"op": "set_material_included", "material": material, "included": False})

    for match in re.finditer(r"(?:删除|去掉|移除)([^。；;，,]+)", compact):
        material = _clean_material_name(match.group(1))
        if material:
            patches.append({"op": "delete_material", "material": material})

    patches = _dedupe_patches(patches)
    if not patches:
        return _response(
            "clarify",
            message="我还没有识别到可修改的报价字段，请说具体一点，例如“数量改300”“毛利改30%”或“PU料按6.5”。",
        )

    return _response("patch_draft", patches, "已按你的描述更新报价草稿，并重新试算。", True)
ALLOWED_GPT_INTENTS = {"patch_draft", "confirm_save", "recalculate", "clarify", "unknown"}
ALLOWED_GPT_PATCH_OPS = {
    "set_quantities",
    "set_margin",
    "set_processing_fee",
    "set_material_price",
    "set_material_usage",
    "set_material_included",
    "set_include_tax",
    "set_include_fob",
    "delete_material",
}
FORBIDDEN_GPT_FIELDS = {
    "quote_result",
    "price",
    "cost",
    "exw",
    "fob",
    "profit",
    "approval_status",
    "final_quote",
    "quote_id",
}


def _clarify_from_gpt(message: str = "") -> dict[str, Any]:
    return _response(
        "clarify",
        message=message or "请说具体一点，例如要修改哪个材料、单价或用量。",
    )


def _gpt_enabled() -> bool:
    return str(os.environ.get("QUOTE_DRAFT_GPT_PATCH_ENABLED") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _contains_forbidden_field(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).strip().lower() in FORBIDDEN_GPT_FIELDS:
                return True
            if _contains_forbidden_field(item):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_field(item) for item in value)
    return False


def _as_non_negative_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _parse_gpt_json_object(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, dict):
        return raw
    text = str(raw or "").strip()
    if text.startswith("```"):
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def validate_gpt_patch_response(raw: Any) -> dict[str, Any]:
    data = _parse_gpt_json_object(raw)
    if not isinstance(data, dict) or _contains_forbidden_field(data):
        return _clarify_from_gpt()

    intent = str(data.get("intent") or "").strip()
    if intent not in ALLOWED_GPT_INTENTS:
        return _clarify_from_gpt()
    if intent == "unknown":
        intent = "clarify"

    patches_raw = data.get("patches")
    if patches_raw is None:
        patches_raw = []
    if not isinstance(patches_raw, list):
        return _clarify_from_gpt()
    if intent in {"confirm_save", "recalculate", "clarify"}:
        if patches_raw:
            return _clarify_from_gpt()
        return _response(
            intent,
            [],
            str(data.get("assistant_message") or "").strip(),
            recalc=(intent == "recalculate"),
        )
    if intent != "patch_draft":
        return _clarify_from_gpt()

    patches: list[dict[str, Any]] = []
    for patch in patches_raw:
        if not isinstance(patch, dict) or _contains_forbidden_field(patch):
            return _clarify_from_gpt()
        op = str(patch.get("op") or "").strip()
        if op not in ALLOWED_GPT_PATCH_OPS:
            return _clarify_from_gpt()
        if op == "set_quantities":
            quantities = patch.get("quantities")
            if not isinstance(quantities, list) or not quantities:
                return _clarify_from_gpt()
            out: list[int] = []
            for item in quantities:
                if isinstance(item, bool) or not isinstance(item, int):
                    return _clarify_from_gpt()
                q = item
                if q <= 0:
                    return _clarify_from_gpt()
                out.append(q)
            patches.append({"op": op, "quantities": out})
        elif op == "set_margin":
            value = _as_non_negative_number(patch.get("gross_margin_rate"))
            if value is None:
                return _clarify_from_gpt()
            rate = value / 100.0 if value > 1 else value
            if not (0 <= rate <= 1):
                return _clarify_from_gpt()
            patches.append({"op": op, "gross_margin_rate": rate})
        elif op == "set_processing_fee":
            value = _as_non_negative_number(patch.get("processing_fee"))
            if value is None:
                return _clarify_from_gpt()
            patches.append({"op": op, "processing_fee": value})
        elif op == "set_material_price":
            material = str(patch.get("material") or "").strip()
            value = _as_non_negative_number(patch.get("unit_price"))
            if not material or value is None:
                return _clarify_from_gpt()
            patches.append({"op": op, "material": material, "unit_price": value})
        elif op == "set_material_usage":
            material = str(patch.get("material") or "").strip()
            value = _as_non_negative_number(patch.get("usage"))
            if not material or value is None:
                return _clarify_from_gpt()
            patches.append({"op": op, "material": material, "usage": value})
        elif op == "set_material_included":
            material = str(patch.get("material") or "").strip()
            included = patch.get("included")
            if not material or not isinstance(included, bool):
                return _clarify_from_gpt()
            patches.append({"op": op, "material": material, "included": included})
        elif op == "set_include_tax":
            include_tax = patch.get("include_tax")
            if not isinstance(include_tax, bool):
                return _clarify_from_gpt()
            patches.append({"op": op, "include_tax": include_tax})
        elif op == "set_include_fob":
            include_fob = patch.get("include_fob")
            if not isinstance(include_fob, bool):
                return _clarify_from_gpt()
            patches.append({"op": op, "include_fob": include_fob})
        elif op == "delete_material":
            material = str(patch.get("material") or "").strip()
            if not material:
                return _clarify_from_gpt()
            patches.append({"op": op, "material": material})

    if not patches:
        return _clarify_from_gpt()
    return _response(
        "patch_draft",
        _dedupe_patches(patches),
        str(data.get("assistant_message") or "已理解为修改报价草稿。").strip(),
        recalc=True,
    )


def build_gpt_patch_prompt(user_text: str, draft: dict | None = None) -> list[dict[str, str]]:
    draft_summary: dict[str, Any] = {}
    if isinstance(draft, dict):
        draft_summary = {
            "product_name": draft.get("product_name"),
            "quantities": draft.get("quantities"),
            "materials": [
                {
                    "name": item.get("name") or item.get("material"),
                    "included_in_quote": item.get("included_in_quote"),
                }
                for item in (draft.get("items") or [])[:30]
                if isinstance(item, dict)
            ],
            "missing_fields": draft.get("missing_fields") or [],
            "risk_flags": draft.get("risk_flags") or [],
        }
    system = (
        "你是报价草稿 patch 解析器。只把用户自然语言转换成 JSON object。"
        "不能计算报价、成本、EXW、FOB、利润、税费、审批状态，不能保存或审批报价。"
        "只能输出 JSON object，不能输出 Markdown 或解释正文。"
        "允许 intent: patch_draft, confirm_save, recalculate, clarify, unknown。"
        "允许 patch op: set_quantities, set_margin, set_processing_fee, "
        "set_material_price, set_material_usage, set_material_included, "
        "set_include_tax, set_include_fob, delete_material。"
        "set_include_tax 只能输出 include_tax 布尔值；set_include_fob 只能输出 include_fob 布尔值。"
        "不确定时返回 clarify 且 patches 为空。"
    )
    user = json.dumps({"user_text": str(user_text or ""), "draft_summary": draft_summary}, ensure_ascii=False)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _call_gpt_patch_model(messages: list[dict[str, str]]) -> str:
    from kimi_client import _base_llm_status, _call_kimi_with_fallback, get_kimi_config

    config = get_kimi_config()
    model = str(os.environ.get("QUOTE_DRAFT_GPT_MODEL") or config.model).strip() or config.model
    timeout_raw = str(os.environ.get("QUOTE_DRAFT_GPT_TIMEOUT_SECONDS") or "").strip()
    timeout_s = config.timeout_s
    if timeout_raw:
        try:
            timeout_s = max(3, min(int(float(timeout_raw)), 60))
        except ValueError:
            timeout_s = config.timeout_s
    config = config.__class__(
        api_key=config.api_key,
        api_key_source=config.api_key_source,
        base_url=config.base_url,
        model=model,
        timeout_s=timeout_s,
        temperature=config.temperature,
    )
    body = {
        "model": config.model,
        "messages": messages,
        "temperature": config.temperature,
        "max_completion_tokens": 512,
        "response_format": {"type": "json_object"},
    }
    raw, status = _call_kimi_with_fallback(body, config, _base_llm_status(config))
    if raw is None:
        raise RuntimeError(str(status.get("error") or "gpt_patch_failed"))
    payload = json.loads(raw)
    return str(payload["choices"][0]["message"]["content"])


def parse_quote_draft_patches_by_gpt(user_text: str, draft: dict | None = None) -> dict[str, Any]:
    try:
        raw = _call_gpt_patch_model(build_gpt_patch_prompt(user_text, draft))
    except Exception:
        return _clarify_from_gpt()
    return validate_gpt_patch_response(raw)


def parse_quote_draft_patches(user_text: str, draft: dict | None = None) -> dict[str, Any]:
    rules = parse_quote_draft_patches_by_rules(user_text, draft)
    if rules.get("intent") in {"patch_draft", "confirm_save", "recalculate"}:
        return rules
    if not _gpt_enabled():
        return rules
    gpt = parse_quote_draft_patches_by_gpt(user_text, draft)
    if gpt.get("intent") in {"patch_draft", "confirm_save", "recalculate", "clarify"}:
        return gpt
    return rules
