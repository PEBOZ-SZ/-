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


def validate_quote_qa_input(input_data: dict) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(input_data, dict):
        raise ValueError("输入必须是 dict。")

    user_context = normalize_user_context(input_data.get("user_context"))
    query = input_data.get("query")
    if not isinstance(query, dict):
        raise ValueError("query 必须是 dict。")

    user_text = str(query.get("user_text") or "").strip()
    if not user_text:
        raise ValueError("query.user_text 必须是非空字符串。")
    if len(user_text) > 2000:
        raise ValueError("query.user_text 长度不能超过 2000 字。")

    sid = query.get("sid")
    if sid is None or str(sid).strip() == "":
        sid = user_context.get("session_id")
    if sid is not None:
        sid = str(sid).strip() or None

    return user_context, {
        "user_text": user_text,
        "sid": sid,
    }


QUOTE_EXPLAIN_AUDIENCES = {"sales_internal", "customer_friendly", "factory_review"}


def validate_quote_explain_input(input_data: dict) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(input_data, dict):
        raise ValueError("输入必须是 dict。")

    user_context = normalize_user_context(input_data.get("user_context"))
    query = input_data.get("query")
    if not isinstance(query, dict):
        raise ValueError("query 必须是 dict。")

    user_question = str(query.get("user_question") or "").strip()
    if not user_question:
        raise ValueError("query.user_question 必须是非空字符串。")
    if len(user_question) > 1000:
        raise ValueError("query.user_question 长度不能超过 1000 字。")

    quote_result = query.get("quote_result")
    if not isinstance(quote_result, dict) or not quote_result:
        raise ValueError("query.quote_result 必须是非空 dict。")

    audience = str(query.get("audience") or "sales_internal").strip() or "sales_internal"
    if audience not in QUOTE_EXPLAIN_AUDIENCES:
        raise ValueError("query.audience 只允许 sales_internal/customer_friendly/factory_review。")

    return user_context, {
        "user_question": user_question,
        "quote_result": quote_result,
        "audience": audience,
    }
