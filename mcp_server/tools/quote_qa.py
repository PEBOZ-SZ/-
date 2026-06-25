from __future__ import annotations

from typing import Any

from mcp_server.audit import write_audit_log
from mcp_server.auth import require_tool_permission
from mcp_server.sanitizer import sanitize_quote_qa_result
from mcp_server.schemas import normalize_user_context, validate_quote_qa_input


TOOL_NAME = "quote_qa"
MODE = "readonly"

BLOCKED_INTENT_KEYWORDS = (
    "重新报价",
    "生成报价",
    "算一下多少钱",
    "帮我报价",
    "保存",
    "导出",
    "审批",
    "修改价格库",
    "改价格库",
    "删除报价",
    "改加工费",
    "改毛利",
    "改单价",
)

BLOCKED_INTENT_ERROR = (
    "quote_qa 只提供只读业务答疑；该请求需要走报价计算、保存、审批或价格库管理工具。"
)


def _is_blocked_intent(user_text: str) -> bool:
    text = str(user_text or "")
    return any(keyword in text for keyword in BLOCKED_INTENT_KEYWORDS)


def _audit_record(
    user_context: dict[str, Any],
    query: Any,
    success: bool,
    blocked: bool = False,
    source_type: str = "",
    error: str | None = None,
) -> dict[str, Any]:
    query_dict = query if isinstance(query, dict) else {}
    user_text = str(query_dict.get("user_text") or "")
    return {
        "tool": TOOL_NAME,
        "user_id": user_context.get("user_id"),
        "role": user_context.get("role", "guest"),
        "session_id": user_context.get("session_id"),
        "text_length": len(user_text),
        "blocked": blocked,
        "source_type": source_type,
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


def quote_qa(input_data: dict) -> dict:
    user_context = normalize_user_context(
        input_data.get("user_context") if isinstance(input_data, dict) else {}
    )
    query = input_data.get("query") if isinstance(input_data, dict) else None

    try:
        require_tool_permission(user_context, TOOL_NAME)
        user_context, query = validate_quote_qa_input(input_data)

        if _is_blocked_intent(query["user_text"]):
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

        from qa_rag import answer_qa

        result = answer_qa(query["user_text"], sid=query.get("sid"))
        sanitized = sanitize_quote_qa_result(result, user_context.get("role", "sales"))
        write_audit_log(
            _audit_record(
                user_context,
                query,
                success=True,
                blocked=False,
                source_type=sanitized.get("source_type", ""),
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
