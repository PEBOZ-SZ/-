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
