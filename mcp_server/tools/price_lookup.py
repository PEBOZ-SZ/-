from __future__ import annotations

from typing import Any

from mcp_server.audit import write_audit_log
from mcp_server.auth import require_tool_permission
from mcp_server.sanitizer import sanitize_price_lookup_result
from mcp_server.schemas import normalize_user_context, validate_price_lookup_input


TOOL_NAME = "price_lookup"
MODE = "readonly"


def _hit_to_dict(hit: Any) -> dict[str, Any]:
    entry = getattr(hit, "entry", None)
    return {
        "name": getattr(entry, "raw_name", ""),
        "spec": getattr(entry, "raw_spec", ""),
        "price": getattr(entry, "raw_price", ""),
        "unit_price_value": getattr(entry, "unit_price_value", None),
        "unit_price_unit": getattr(entry, "unit_price_unit", ""),
        "score": getattr(hit, "score", None),
        "auto_learned": bool(getattr(entry, "auto_learned", False)),
    }


def _audit_record(
    user_context: dict[str, Any],
    query: Any,
    success: bool,
    hit_count: int = 0,
    error: str | None = None,
) -> dict[str, Any]:
    query_dict = query if isinstance(query, dict) else {}
    return {
        "tool": TOOL_NAME,
        "user_id": user_context.get("user_id"),
        "role": user_context.get("role", "guest"),
        "session_id": user_context.get("session_id"),
        "query_name": query_dict.get("name"),
        "query_spec": query_dict.get("spec"),
        "limit": query_dict.get("limit"),
        "hit_count": hit_count,
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


def price_lookup(input_data: dict) -> dict:
    user_context = normalize_user_context(
        input_data.get("user_context") if isinstance(input_data, dict) else {}
    )
    query = input_data.get("query") if isinstance(input_data, dict) else None

    try:
        require_tool_permission(user_context, TOOL_NAME)
        user_context, query = validate_price_lookup_input(input_data)

        from price_kb import get_price_kb

        kb = get_price_kb()
        hits = kb.lookup_ranked(
            query["name"],
            query.get("spec", ""),
            limit=query.get("limit", 5),
            min_score=query.get("min_score"),
        )
        result = {
            "query": {
                "name": query["name"],
                "spec": query.get("spec", ""),
            },
            "hits": [_hit_to_dict(hit) for hit in hits],
        }
        sanitized = sanitize_price_lookup_result(result, user_context.get("role", "sales"))
        write_audit_log(
            _audit_record(
                user_context,
                query,
                success=True,
                hit_count=sanitized.get("hit_count", 0),
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
