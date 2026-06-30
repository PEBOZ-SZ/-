from __future__ import annotations

import copy
import json
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


DRAFT_STORE_PATH = Path(__file__).resolve().parent / "data" / "quote_drafts.json"
_LOCK = threading.RLock()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _read_all() -> dict[str, dict[str, Any]]:
    if not DRAFT_STORE_PATH.exists():
        return {}
    try:
        data = json.loads(DRAFT_STORE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_all(data: dict[str, dict[str, Any]]) -> None:
    DRAFT_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = DRAFT_STORE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(DRAFT_STORE_PATH)


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text in {"-", "—"}:
        return None
    import re

    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _as_rate(value: Any, fallback: float = 0.35) -> float:
    num = _as_float(value)
    if num is None:
        return fallback
    return num / 100.0 if num > 1 else num


def _quantities_from(*sources: Any) -> list[int]:
    out: list[int] = []
    for value in sources:
        if isinstance(value, list):
            for item in value:
                try:
                    q = int(float(str(item).strip()))
                except (TypeError, ValueError):
                    continue
                if q > 0 and q not in out:
                    out.append(q)
        elif isinstance(value, tuple):
            for item in value:
                try:
                    q = int(float(str(item).strip()))
                except (TypeError, ValueError):
                    continue
                if q > 0 and q not in out:
                    out.append(q)
    return out


def _items_from(source_payload: dict[str, Any], quote_result: dict[str, Any]) -> list[dict[str, Any]]:
    raw_items = source_payload.get("items")
    if not isinstance(raw_items, list):
        raw_items = quote_result.get("detail_rows")
    items: list[dict[str, Any]] = []
    if not isinstance(raw_items, list):
        return items
    for row in raw_items:
        if not isinstance(row, dict):
            continue
        item = copy.deepcopy(row)
        name = str(item.get("name") or item.get("material") or "").strip()
        if not name:
            continue
        item["name"] = name
        if "included_in_quote" not in item:
            excluded = bool(item.get("exclude_from_cost")) or str(item.get("recognition_status") or "") == "ignored"
            item["included_in_quote"] = not excluded
        items.append(item)
    return items


def _collect_list(*values: Any) -> list[str]:
    out: list[str] = []
    for value in values:
        if isinstance(value, list):
            for item in value:
                text = str(item or "").strip()
                if text and text not in out:
                    out.append(text)
        elif isinstance(value, dict):
            for item in value.values():
                text = str(item or "").strip()
                if text and text not in out:
                    out.append(text)
        else:
            text = str(value or "").strip()
            if text and text not in out:
                out.append(text)
    return out


def _draft_from(session_id: str, source_payload: dict[str, Any] | None, quote_result: dict[str, Any] | None) -> dict[str, Any]:
    source_payload = copy.deepcopy(source_payload) if isinstance(source_payload, dict) else {}
    quote_result = copy.deepcopy(quote_result) if isinstance(quote_result, dict) else {}
    settings = quote_result.get("settings") if isinstance(quote_result.get("settings"), dict) else {}
    quantities = _quantities_from(
        source_payload.get("quantities"),
        [tier.get("quantity") for tier in quote_result.get("tiers", []) if isinstance(tier, dict)]
        if isinstance(quote_result.get("tiers"), list)
        else None,
    )
    return {
        "draft_id": f"draft_{uuid.uuid4().hex[:12]}",
        "session_id": session_id,
        "product_name": str(
            source_payload.get("product_name") or quote_result.get("product_name") or ""
        ).strip(),
        "quantities": quantities or [300],
        "items": _items_from(source_payload, quote_result),
        "materials": _items_from(source_payload, quote_result),
        "processing_fee": _as_float(source_payload.get("processing_fee", settings.get("processing_fee"))) or 12,
        "gross_margin_rate": _as_rate(
            source_payload.get("gross_margin_rate", settings.get("gross_margin_rate")),
            0.35,
        ),
        "include_tax": bool(source_payload.get("include_tax", quote_result.get("include_tax", False))),
        "include_fob": bool(source_payload.get("include_fob", quote_result.get("include_fob", settings.get("include_fob", True)))),
        "incoterms": str(source_payload.get("incoterms") or quote_result.get("incoterms") or "").strip(),
        "missing_fields": _collect_list(
            source_payload.get("missing_fields"),
            quote_result.get("missing_fields"),
            quote_result.get("validation_errors"),
        ),
        "risk_flags": _collect_list(source_payload.get("risk_flags"), quote_result.get("risk_flags")),
        "source_quote_result": quote_result,
        "source_payload": source_payload,
        "updated_at": _now(),
    }


def create_quote_draft(
    session_id: str,
    source_payload: dict[str, Any] | None = None,
    quote_result: dict[str, Any] | None = None,
) -> dict:
    sid = str(session_id or "").strip()
    if not sid:
        raise ValueError("session_id is required")
    with _LOCK:
        data = _read_all()
        draft = _draft_from(sid, source_payload, quote_result)
        data[sid] = draft
        _write_all(data)
        return copy.deepcopy(draft)


def get_quote_draft(session_id: str) -> dict | None:
    sid = str(session_id or "").strip()
    if not sid:
        return None
    with _LOCK:
        draft = _read_all().get(sid)
        return copy.deepcopy(draft) if isinstance(draft, dict) else None


def _material_matches(item: dict[str, Any], name: str) -> bool:
    target = str(name or "").strip().lower()
    if not target:
        return False
    item_name = str(item.get("name") or item.get("material") or "").strip().lower()
    return bool(item_name and (target in item_name or item_name in target))


def _touch_material(draft: dict[str, Any], material: str) -> list[dict[str, Any]]:
    items = draft.setdefault("items", [])
    if not isinstance(items, list):
        draft["items"] = items = []
    matches = [item for item in items if isinstance(item, dict) and _material_matches(item, material)]
    if matches:
        return matches
    item = {"name": material, "usage": "", "unit_price": "", "amount": 0, "included_in_quote": True}
    items.append(item)
    return [item]


def _clear_resolved_risks(draft: dict[str, Any], material: str = "") -> None:
    if not material:
        return
    target = material.strip()
    for key in ("risk_flags", "missing_fields"):
        values = draft.get(key)
        if not isinstance(values, list):
            continue
        draft[key] = [text for text in values if target not in str(text)]


def update_quote_draft(session_id: str, patches: list[dict]) -> dict:
    sid = str(session_id or "").strip()
    if not sid:
        raise ValueError("session_id is required")
    with _LOCK:
        data = _read_all()
        draft = data.get(sid)
        if not isinstance(draft, dict):
            raise KeyError(f"quote draft not found: {sid}")
        for patch in patches or []:
            if not isinstance(patch, dict):
                continue
            op = str(patch.get("op") or "").strip()
            if op == "set_quantities":
                qs = _quantities_from(patch.get("quantities"))
                if qs:
                    draft["quantities"] = qs
            elif op == "set_margin":
                draft["gross_margin_rate"] = _as_rate(patch.get("gross_margin_rate"), draft.get("gross_margin_rate", 0.35))
            elif op == "set_processing_fee":
                value = _as_float(patch.get("processing_fee"))
                if value is not None:
                    draft["processing_fee"] = value
            elif op == "set_include_tax":
                value = patch.get("include_tax")
                if isinstance(value, bool):
                    draft["include_tax"] = value
            elif op == "set_include_fob":
                value = patch.get("include_fob")
                if isinstance(value, bool):
                    draft["include_fob"] = value
            elif op in {"set_material_price", "set_material_usage", "set_material_included"}:
                material = str(patch.get("material") or "").strip()
                if not material:
                    continue
                for item in _touch_material(draft, material):
                    if op == "set_material_price":
                        item["unit_price"] = patch.get("unit_price")
                        item["unit_price_source"] = "user_input"
                    elif op == "set_material_usage":
                        item["usage"] = patch.get("usage")
                        item["usage_source"] = "user_input"
                    elif op == "set_material_included":
                        included = bool(patch.get("included"))
                        item["included_in_quote"] = included
                        item["exclude_from_cost"] = not included
                        if included and str(item.get("recognition_status") or "") == "ignored":
                            item["recognition_status"] = "confirmed"
                        elif not included:
                            item["recognition_status"] = "ignored"
                    _clear_resolved_risks(draft, material)
            elif op == "delete_material":
                material = str(patch.get("material") or "").strip()
                if material and isinstance(draft.get("items"), list):
                    draft["items"] = [
                        item
                        for item in draft["items"]
                        if not (isinstance(item, dict) and _material_matches(item, material))
                    ]
                    _clear_resolved_risks(draft, material)
            elif op == "set_source_quote_result" and isinstance(patch.get("quote_result"), dict):
                draft["source_quote_result"] = copy.deepcopy(patch["quote_result"])
        draft["materials"] = copy.deepcopy(draft.get("items") if isinstance(draft.get("items"), list) else [])
        draft["updated_at"] = _now()
        data[sid] = draft
        _write_all(data)
        return copy.deepcopy(draft)


def clear_quote_draft(session_id: str) -> None:
    sid = str(session_id or "").strip()
    if not sid:
        return
    with _LOCK:
        data = _read_all()
        data.pop(sid, None)
        _write_all(data)


def quote_draft_to_calculate_payload(draft: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(draft.get("source_payload") if isinstance(draft.get("source_payload"), dict) else {})
    payload.update(
        {
            "product_name": draft.get("product_name") or payload.get("product_name") or "",
            "quantities": list(draft.get("quantities") or [300]),
            "items": copy.deepcopy(draft.get("items") if isinstance(draft.get("items"), list) else []),
            "processing_fee": draft.get("processing_fee"),
            "gross_margin_rate": draft.get("gross_margin_rate"),
            "include_fob": draft.get("include_fob"),
            "include_tax": draft.get("include_tax"),
            "incoterms": draft.get("incoterms"),
            "quote_mode": payload.get("quote_mode") or "draft_mode",
        }
    )
    return payload
