from __future__ import annotations


def require_tool_permission(user_context: dict, tool_name: str) -> None:
    """Raise PermissionError when the current role cannot call a tool."""
    context = user_context if isinstance(user_context, dict) else {}
    role = str(context.get("role") or "guest").strip() or "guest"

    if tool_name in {"quote_calculate", "price_lookup"} and role in {"sales", "admin"}:
        return

    raise PermissionError(f"当前角色无权调用 {tool_name}。")
