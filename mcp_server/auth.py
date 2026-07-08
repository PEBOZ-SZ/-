from __future__ import annotations

from typing import Any


ROLE_GUEST = "guest"
ROLE_SALES = "sales"
ROLE_ADMIN = "admin"
ROLE_SYSTEM_ADMIN = "system_admin"

KNOWN_ROLES = {
    ROLE_GUEST,
    ROLE_SALES,
    ROLE_ADMIN,
    ROLE_SYSTEM_ADMIN,
}

MCP_TOOL_PERMISSIONS: dict[str, set[str]] = {
    "quote_calculate": {ROLE_SALES, ROLE_ADMIN, ROLE_SYSTEM_ADMIN},
    "quote_save": {ROLE_SALES, ROLE_ADMIN, ROLE_SYSTEM_ADMIN},
    "quote_export": {ROLE_SALES, ROLE_ADMIN, ROLE_SYSTEM_ADMIN},
    "quote_export_pdf": {ROLE_SALES, ROLE_ADMIN, ROLE_SYSTEM_ADMIN},
    "quote_approval_status": {ROLE_SALES, ROLE_ADMIN, ROLE_SYSTEM_ADMIN},
    "quote_get_history": {ROLE_SALES, ROLE_ADMIN, ROLE_SYSTEM_ADMIN},
    "quote_get_detail": {ROLE_SALES, ROLE_ADMIN, ROLE_SYSTEM_ADMIN},
    "quote_sheet_preview": {ROLE_GUEST, ROLE_SALES, ROLE_ADMIN, ROLE_SYSTEM_ADMIN},
    "quote_explain": {ROLE_SALES, ROLE_ADMIN, ROLE_SYSTEM_ADMIN},
    "quote_patch_preview": {ROLE_SALES, ROLE_ADMIN, ROLE_SYSTEM_ADMIN},
    "quote_qa": {ROLE_SALES, ROLE_ADMIN, ROLE_SYSTEM_ADMIN},
    "price_lookup": {ROLE_SALES, ROLE_ADMIN, ROLE_SYSTEM_ADMIN},
    "quote_admin": {ROLE_ADMIN, ROLE_SYSTEM_ADMIN},
    "price_update": {ROLE_SYSTEM_ADMIN},
    "knowledge_apply": {ROLE_SYSTEM_ADMIN},
    "mcp_audit_view": {ROLE_SYSTEM_ADMIN},
}

QUOTE_ADMIN_ACTION_PERMISSIONS: dict[str, set[str]] = {
    "approve_quote": {ROLE_ADMIN, ROLE_SYSTEM_ADMIN},
    "reject_quote": {ROLE_ADMIN, ROLE_SYSTEM_ADMIN},
    "freeze_quote": {ROLE_ADMIN, ROLE_SYSTEM_ADMIN},
    "unfreeze_quote": {ROLE_ADMIN, ROLE_SYSTEM_ADMIN},
    "mark_exported": {ROLE_ADMIN, ROLE_SYSTEM_ADMIN},
    "update_price_rule": {ROLE_SYSTEM_ADMIN},
    "view_quote": {ROLE_ADMIN, ROLE_SYSTEM_ADMIN},
}


def normalize_role(role: Any) -> str:
    """Return a known MCP role, treating missing or unknown roles as guest."""
    value = str(role or ROLE_GUEST).strip() or ROLE_GUEST
    return value if value in KNOWN_ROLES else ROLE_GUEST


def require_tool_permission(user_context: dict, tool_name: str, action: str | None = None) -> None:
    """Raise PermissionError when the current role cannot call a tool/action."""
    context = user_context if isinstance(user_context, dict) else {}
    role = normalize_role(context.get("role"))

    allowed_roles = MCP_TOOL_PERMISSIONS.get(tool_name, set())
    if role not in allowed_roles:
        raise PermissionError(f"当前角色无权调用 {tool_name}。")

    if tool_name == "quote_admin" and action:
        allowed_action_roles = QUOTE_ADMIN_ACTION_PERMISSIONS.get(action, set())
        if role not in allowed_action_roles:
            raise PermissionError(f"当前角色无权调用 {tool_name}。")


def require_quote_access(user_context: dict, quote_uid: str, action: str) -> None:
    """Reserve the quote ownership gate for future MCP history/export flows.

    Future tools such as quote_preview, quote_export, quote_approval_status and
    quote_feedback_inbox must connect this function to the original storage
    layer. Sales access must be checked by sales_user_id ownership; admin and
    system_admin should follow backend management permissions.
    """
    context = user_context if isinstance(user_context, dict) else {}
    role = normalize_role(context.get("role"))
    if role in {ROLE_ADMIN, ROLE_SYSTEM_ADMIN}:
        return
    if role == ROLE_SALES:
        raise NotImplementedError(
            f"报价访问校验尚未接入存储层，sales 必须按 sales_user_id 校验报价归属：{quote_uid} {action}"
        )
    raise PermissionError("当前角色无权访问报价。")
