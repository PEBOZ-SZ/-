from __future__ import annotations

from typing import Any


ALLOWED_QUOTE_CALCULATE_ROLES = {"sales", "admin"}


def normalize_user_context(user_context: Any) -> dict[str, Any]:
    context = dict(user_context) if isinstance(user_context, dict) else {}
    role = str(context.get("role") or "guest").strip() or "guest"
    context["role"] = role
    return context


def validate_quote_calculate_input(input_data: dict) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(input_data, dict):
        raise ValueError("输入必须是 dict。")

    user_context = normalize_user_context(input_data.get("user_context"))
    payload = input_data.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("payload 必须是 dict。")

    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("缺少明细 items，无法试算报价。")

    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict) or not str(item.get("name") or "").strip():
            raise ValueError(f"第 {index} 条明细缺少 name 字段。")

    return user_context, payload


def validate_price_lookup_input(input_data: dict) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(input_data, dict):
        raise ValueError("输入必须是 dict。")

    user_context = normalize_user_context(input_data.get("user_context"))
    query = input_data.get("query")
    if not isinstance(query, dict):
        raise ValueError("query 必须是 dict。")

    name = str(query.get("name") or "").strip()
    if not name:
        raise ValueError("query.name 必须是非空字符串。")

    spec = str(query.get("spec") or "").strip()

    try:
        limit = int(query.get("limit", 5))
    except (TypeError, ValueError):
        raise ValueError("query.limit 必须是整数。") from None
    limit = max(1, min(10, limit))

    raw_min_score = query.get("min_score")
    min_score = None
    if raw_min_score is not None:
        try:
            min_score = float(raw_min_score)
        except (TypeError, ValueError):
            raise ValueError("query.min_score 必须是数字或 null。") from None
        min_score = max(0.05, min(0.99, min_score))

    return user_context, {
        "name": name,
        "spec": spec,
        "limit": limit,
        "min_score": min_score,
    }
