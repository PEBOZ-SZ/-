from __future__ import annotations

from typing import Any

from mcp_server.audit import write_audit_log
from mcp_server.auth import require_tool_permission
from mcp_server.sanitizer import sanitize_quote_explain_result
from mcp_server.schemas import normalize_user_context, validate_quote_explain_input


TOOL_NAME = "quote_explain"
MODE = "readonly"

BLOCKED_INTENT_KEYWORDS = (
    "重新报价",
    "生成报价",
    "帮我报价",
    "算一下多少钱",
    "重新算",
    "改加工费",
    "改毛利",
    "改单价",
    "修改价格",
    "保存",
    "导出",
    "审批",
    "修改价格库",
    "改价格库",
    "删除报价",
)

BLOCKED_INTENT_ERROR = (
    "quote_explain 只解释已有报价结果；该请求需要走报价计算、局部试算、保存、审批或价格库管理工具。"
)


def _is_blocked_intent(user_question: str) -> bool:
    text = str(user_question or "")
    return any(keyword in text for keyword in BLOCKED_INTENT_KEYWORDS)


def _audit_record(
    user_context: dict[str, Any],
    query: Any,
    success: bool,
    blocked: bool = False,
    fallback_used: bool = False,
    error: str | None = None,
) -> dict[str, Any]:
    query_dict = query if isinstance(query, dict) else {}
    quote_result = query_dict.get("quote_result") if isinstance(query_dict.get("quote_result"), dict) else {}
    tiers = quote_result.get("tiers")
    items = quote_result.get("items")
    return {
        "tool": TOOL_NAME,
        "user_id": user_context.get("user_id"),
        "role": user_context.get("role", "guest"),
        "session_id": user_context.get("session_id"),
        "audience": query_dict.get("audience"),
        "text_length": len(str(query_dict.get("user_question") or "")),
        "quote_result_present": bool(quote_result),
        "tier_count": len(tiers) if isinstance(tiers, list) else 0,
        "item_count": len(items) if isinstance(items, list) else 0,
        "blocked": blocked,
        "fallback_used": fallback_used,
        "success": success,
        "error": error,
    }


def _failure(error: str) -> dict[str, Any]:
    return {
        "ok": False,
        "tool": TOOL_NAME,
        "mode": MODE,
        "error": error,
    }


def quote_explain(input_data: dict) -> dict:
    user_context = normalize_user_context(
        input_data.get("user_context") if isinstance(input_data, dict) else {}
    )
    query = input_data.get("query") if isinstance(input_data, dict) else None

    try:
        require_tool_permission(user_context, TOOL_NAME)
        user_context, query = validate_quote_explain_input(input_data)

        if _is_blocked_intent(query["user_question"]):
            write_audit_log(
                _audit_record(
                    user_context,
                    query,
                    success=False,
                    blocked=True,
                    error=BLOCKED_INTENT_ERROR,
                )
            )
            return _failure(BLOCKED_INTENT_ERROR)

        from quote_explain import (
            build_quote_explain_facts,
            build_quote_explain_fallback_text,
            generate_quote_explain_with_llm,
        )

        facts = build_quote_explain_facts(query["quote_result"])
        fallback_used = False
        try:
            answer = generate_quote_explain_with_llm(
                user_question=query["user_question"],
                quote_result_facts=facts,
                audience=query["audience"],
            )
            if not answer:
                raise RuntimeError("empty_llm_reply")
        except Exception:
            answer = build_quote_explain_fallback_text(
                query["quote_result"],
                user_question=query["user_question"],
                quote_result_facts=facts,
            )
            fallback_used = True

        sanitized = sanitize_quote_explain_result(
            {
                "answer": answer,
                "audience": query["audience"],
                "used_quote_result": True,
                "number_policy": "quote_result_only",
                "fallback_used": fallback_used,
            },
            user_context.get("role", "sales"),
        )
        write_audit_log(
            _audit_record(
                user_context,
                query,
                success=True,
                blocked=False,
                fallback_used=fallback_used,
            )
        )
        return {
            "ok": True,
            "tool": TOOL_NAME,
            "mode": MODE,
            "result": sanitized,
        }
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
        try:
            write_audit_log(_audit_record(user_context, query, success=False, error=error))
        except Exception:
            pass
        return _failure(error)
