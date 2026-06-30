from __future__ import annotations

from typing import Any

from mcp_server.auth import normalize_role


ALLOWED_QUOTE_CALCULATE_ROLES = {"sales", "admin"}
USER_CONTEXT_FIELDS = {
    "user_id",
    "user_name",
    "role",
    "session_id",
    "sales_user_id",
    "sales_user_name",
    "sales_user_code",
    "source",
    "request_id",
}


def normalize_user_context(user_context: Any) -> dict[str, Any]:
    context = dict(user_context) if isinstance(user_context, dict) else {}
    context["role"] = normalize_role(context.get("role"))
    for field in USER_CONTEXT_FIELDS:
        context.setdefault(field, None)
    return context


def validate_quote_calculate_input(input_data: dict) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(input_data, dict):
        raise ValueError("input_data must be a dict.")

    user_context = normalize_user_context(input_data.get("user_context"))
    payload = input_data.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("payload must be a dict.")

    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("缺少明细 items")

    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict) or not str(item.get("name") or "").strip():
            raise ValueError(f"item {index} is missing name.")

    return user_context, payload


def validate_price_lookup_input(input_data: dict) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(input_data, dict):
        raise ValueError("input_data must be a dict.")

    user_context = normalize_user_context(input_data.get("user_context"))
    query = input_data.get("query")
    if not isinstance(query, dict):
        raise ValueError("query must be a dict.")

    name = str(query.get("name") or "").strip()
    if not name:
        raise ValueError("query.name is required.")

    spec = str(query.get("spec") or "").strip()

    try:
        limit = int(query.get("limit", 5))
    except (TypeError, ValueError):
        raise ValueError("query.limit must be an integer.") from None
    limit = max(1, min(10, limit))

    raw_min_score = query.get("min_score")
    min_score = None
    if raw_min_score is not None:
        try:
            min_score = float(raw_min_score)
        except (TypeError, ValueError):
            raise ValueError("query.min_score must be a number or null.") from None
        min_score = max(0.05, min(0.99, min_score))

    return user_context, {
        "name": name,
        "spec": spec,
        "limit": limit,
        "min_score": min_score,
    }


def validate_quote_qa_input(input_data: dict) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(input_data, dict):
        raise ValueError("input_data must be a dict.")

    user_context = normalize_user_context(input_data.get("user_context"))
    query = input_data.get("query")
    if not isinstance(query, dict):
        raise ValueError("query must be a dict.")

    user_text = str(query.get("user_text") or "").strip()
    if not user_text:
        raise ValueError("query.user_text is required.")
    if len(user_text) > 2000:
        raise ValueError("query.user_text must be at most 2000 characters.")

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
        raise ValueError("input_data must be a dict.")

    user_context = normalize_user_context(input_data.get("user_context"))
    query = input_data.get("query")
    if not isinstance(query, dict):
        raise ValueError("query must be a dict.")

    user_question = str(query.get("user_question") or "").strip()
    if not user_question:
        raise ValueError("query.user_question is required.")
    if len(user_question) > 1000:
        raise ValueError("query.user_question must be at most 1000 characters.")

    quote_result = query.get("quote_result")
    if not isinstance(quote_result, dict) or not quote_result:
        raise ValueError("query.quote_result must be a non-empty dict.")

    audience = str(query.get("audience") or "sales_internal").strip() or "sales_internal"
    if audience not in QUOTE_EXPLAIN_AUDIENCES:
        raise ValueError("query.audience is not supported.")

    return user_context, {
        "user_question": user_question,
        "quote_result": quote_result,
        "audience": audience,
    }


def validate_quote_patch_preview_input(input_data: dict) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(input_data, dict):
        raise ValueError("input_data must be a dict.")

    user_context = normalize_user_context(input_data.get("user_context"))
    query = input_data.get("query")
    if not isinstance(query, dict):
        raise ValueError("query must be a dict.")

    quote_result = query.get("quote_result")
    if not isinstance(quote_result, dict) or not quote_result:
        raise ValueError("query.quote_result must be a non-empty dict.")

    patch = query.get("patch", {})
    if patch is None:
        patch = {}
    if not isinstance(patch, dict):
        raise ValueError("query.patch must be a dict.")

    return user_context, {
        "quote_result": quote_result,
        "patch": dict(patch),
    }


def validate_quote_save_input(input_data: dict) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(input_data, dict):
        raise ValueError("input_data must be a dict.")

    user_context = normalize_user_context(input_data.get("user_context"))
    query = input_data.get("query")
    if not isinstance(query, dict):
        raise ValueError("query must be a dict.")

    quote_result = query.get("quote_result")
    if not isinstance(quote_result, dict) or not quote_result:
        raise ValueError("query.quote_result must be a non-empty dict.")

    return user_context, {"quote_result": quote_result}


def validate_quote_export_input(input_data: dict) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(input_data, dict):
        raise ValueError("input_data must be a dict.")

    user_context = normalize_user_context(input_data.get("user_context"))
    query = input_data.get("query")
    if not isinstance(query, dict):
        raise ValueError("query must be a dict.")

    quote_id = str(query.get("quote_id") or "").strip()
    if not quote_id:
        raise ValueError("query.quote_id is required.")

    return user_context, {"quote_id": quote_id}


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _coerce_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def validate_quote_get_history_input(input_data: dict) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(input_data, dict):
        raise ValueError("input_data must be a dict.")

    user_context = normalize_user_context(input_data.get("user_context"))
    query = input_data.get("query", {})
    if query is None:
        query = {}
    if not isinstance(query, dict):
        raise ValueError("query must be a dict.")

    approval_status = str(query.get("approval_status") or "").strip().lower()
    if approval_status and approval_status not in {"pending", "approved", "rejected"}:
        raise ValueError("query.approval_status is not supported.")

    return user_context, {
        "limit": _coerce_int(query.get("limit"), 20, minimum=1, maximum=100),
        "offset": _coerce_int(query.get("offset"), 0, minimum=0, maximum=100000),
        "keyword": str(query.get("keyword") or "").strip(),
        "approval_status": approval_status,
        "include_hidden": _coerce_bool(query.get("include_hidden"), False),
        "sales_user_id": str(query.get("sales_user_id") or "").strip(),
    }


def validate_quote_get_detail_input(input_data: dict) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(input_data, dict):
        raise ValueError("input_data must be a dict.")

    user_context = normalize_user_context(input_data.get("user_context"))
    query = input_data.get("query")
    if not isinstance(query, dict):
        raise ValueError("query must be a dict.")

    quote_uid = str(query.get("quote_uid") or "").strip()
    calc_quote_id = str(query.get("calc_quote_id") or query.get("quote_id") or "").strip()
    version_id = str(query.get("version_id") or "").strip()
    if not quote_uid and not calc_quote_id and not version_id:
        raise ValueError("query.quote_uid, query.calc_quote_id, or query.version_id is required.")

    raw_version = query.get("version_no")
    version_no = None
    if raw_version not in (None, ""):
        try:
            version_no = int(raw_version)
        except (TypeError, ValueError):
            raise ValueError("query.version_no must be an integer or empty.") from None
        if version_no <= 0:
            raise ValueError("query.version_no must be greater than 0.")

    return user_context, {
        "quote_uid": quote_uid,
        "calc_quote_id": calc_quote_id,
        "version_id": version_id,
        "version_no": version_no,
        "include_quote_json": _coerce_bool(query.get("include_quote_json"), True),
        "include_files": _coerce_bool(query.get("include_files"), True),
        "include_chat_messages": _coerce_bool(query.get("include_chat_messages"), False),
    }


def validate_quote_sheet_preview_input(input_data: dict) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(input_data, dict):
        raise ValueError("input_data must be a dict.")

    user_context = normalize_user_context(input_data.get("user_context"))
    query = input_data.get("query")
    if not isinstance(query, dict):
        raise ValueError("query must be a dict.")

    quote_uid = str(query.get("quote_uid") or "").strip()
    calc_quote_id = str(query.get("calc_quote_id") or query.get("quote_id") or "").strip()
    version_id = str(query.get("version_id") or "").strip()
    if not quote_uid and not calc_quote_id and not version_id:
        raise ValueError("query.quote_uid, query.calc_quote_id, or query.version_id is required.")

    raw_version = query.get("version_no")
    version_no = None
    if raw_version not in (None, ""):
        try:
            version_no = int(raw_version)
        except (TypeError, ValueError):
            raise ValueError("query.version_no must be an integer or empty.") from None
        if version_no <= 0:
            raise ValueError("query.version_no must be greater than 0.")

    mode = str(query.get("mode") or "url").strip().lower() or "url"
    if mode not in {"url", "prefill"}:
        raise ValueError("query.mode must be url or prefill.")

    source = str(query.get("source") or "record").strip().lower() or "record"

    return user_context, {
        "quote_uid": quote_uid,
        "calc_quote_id": calc_quote_id,
        "version_id": version_id,
        "version_no": version_no,
        "mode": mode,
        "source": source,
        "include_prefill": _coerce_bool(query.get("include_prefill"), False),
    }


def validate_quote_export_pdf_input(input_data: dict) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(input_data, dict):
        raise ValueError("input_data must be a dict.")

    user_context = normalize_user_context(input_data.get("user_context"))
    query = input_data.get("query")
    if not isinstance(query, dict):
        raise ValueError("query must be a dict.")

    quote_uid = str(query.get("quote_uid") or "").strip()
    calc_quote_id = str(query.get("calc_quote_id") or query.get("quote_id") or "").strip()
    version_id = str(query.get("version_id") or "").strip()
    if not quote_uid and not calc_quote_id and not version_id:
        raise ValueError("query.quote_uid, query.calc_quote_id, or query.version_id is required.")

    raw_version = query.get("version_no")
    version_no = None
    if raw_version not in (None, ""):
        try:
            version_no = int(raw_version)
        except (TypeError, ValueError):
            raise ValueError("query.version_no must be an integer or empty.") from None
        if version_no <= 0:
            raise ValueError("query.version_no must be greater than 0.")

    lang = str(query.get("lang") or "cn").strip().lower() or "cn"
    if lang not in {"cn", "en", "bilingual"}:
        raise ValueError("query.lang must be cn, en, or bilingual.")

    currency_mode = str(query.get("currency_mode") or "rmb").strip().lower() or "rmb"
    if currency_mode not in {"rmb", "fob_usd"}:
        raise ValueError("query.currency_mode must be rmb or fob_usd.")

    source = str(query.get("source") or "record").strip().lower() or "record"

    return user_context, {
        "quote_uid": quote_uid,
        "calc_quote_id": calc_quote_id,
        "version_id": version_id,
        "version_no": version_no,
        "lang": lang,
        "currency_mode": currency_mode,
        "source": source,
        "dry_run": _coerce_bool(query.get("dry_run"), False),
    }


def validate_quote_approval_status_input(input_data: dict) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(input_data, dict):
        raise ValueError("input_data must be a dict.")

    user_context = normalize_user_context(input_data.get("user_context"))
    query = input_data.get("query")
    if not isinstance(query, dict):
        raise ValueError("query must be a dict.")

    quote_uid = str(query.get("quote_uid") or "").strip()
    calc_quote_id = str(query.get("calc_quote_id") or query.get("quote_id") or "").strip()
    version_id = str(query.get("version_id") or "").strip()
    if not quote_uid and not calc_quote_id and not version_id:
        raise ValueError("query.quote_uid, query.calc_quote_id, or query.version_id is required.")

    raw_version = query.get("version_no")
    version_no = None
    if raw_version not in (None, ""):
        try:
            version_no = int(raw_version)
        except (TypeError, ValueError):
            raise ValueError("query.version_no must be an integer or empty.") from None
        if version_no <= 0:
            raise ValueError("query.version_no must be greater than 0.")

    return user_context, {
        "quote_uid": quote_uid,
        "calc_quote_id": calc_quote_id,
        "version_id": version_id,
        "version_no": version_no,
        "include_admin_feedback": _coerce_bool(query.get("include_admin_feedback"), True),
        "include_export_readiness": _coerce_bool(query.get("include_export_readiness"), True),
    }


QUOTE_ADMIN_ACTIONS = {
    "approve_quote",
    "reject_quote",
    "freeze_quote",
    "unfreeze_quote",
    "mark_exported",
    "update_price_rule",
    "view_quote",
}


def validate_quote_admin_input(input_data: dict) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(input_data, dict):
        raise ValueError("input_data must be a dict.")

    user_context = normalize_user_context(input_data.get("user_context"))
    query = input_data.get("query")
    if not isinstance(query, dict):
        raise ValueError("query must be a dict.")

    action = str(query.get("action") or "").strip()
    if action not in QUOTE_ADMIN_ACTIONS:
        raise ValueError("query.action is not supported.")

    quote_uid = str(query.get("quote_uid") or "").strip()
    calc_quote_id = str(query.get("calc_quote_id") or query.get("quote_id") or "").strip()
    quote_id = str(query.get("quote_id") or "").strip()
    version_id = str(query.get("version_id") or "").strip()
    if action != "update_price_rule" and not quote_uid and not calc_quote_id and not version_id:
        raise ValueError("query.quote_uid, query.calc_quote_id, or query.quote_id is required.")

    raw_version = query.get("version_no")
    version_no = None
    if raw_version not in (None, ""):
        try:
            version_no = int(raw_version)
        except (TypeError, ValueError):
            raise ValueError("query.version_no must be an integer or empty.") from None
        if version_no <= 0:
            raise ValueError("query.version_no must be greater than 0.")

    payload = query.get("payload", {})
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError("query.payload must be a dict.")

    return user_context, {
        "action": action,
        "quote_uid": quote_uid,
        "calc_quote_id": calc_quote_id,
        "quote_id": quote_id,
        "version_id": version_id,
        "version_no": version_no,
        "payload": payload,
    }
