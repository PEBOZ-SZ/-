from __future__ import annotations

from typing import Any, Callable

from mcp_server.tools.quote_admin import quote_admin
from mcp_server.tools.quote_calculate import quote_calculate
from mcp_server.tools.quote_explain import quote_explain
from mcp_server.tools.quote_export import quote_export
from mcp_server.tools.quote_patch_preview import quote_patch_preview
from mcp_server.tools.quote_save import quote_save
from workflow_state_manager import flow_error_response, validate_tool_call


TOOL_REGISTRY: dict[str, Callable[[dict], dict]] = {
    "quote_calculate": quote_calculate,
    "quote_explain": quote_explain,
    "quote_patch_preview": quote_patch_preview,
    "quote_save": quote_save,
    "quote_export": quote_export,
    "quote_admin": quote_admin,
}


def mcp_call(tool_name: str, args: dict[str, Any] | None) -> dict:
    name = str(tool_name or "").strip()
    call_args = args if isinstance(args, dict) else {}
    tool = TOOL_REGISTRY.get(name)
    if tool is None:
        return {"ok": False, "tool": name, "error": f"unsupported MCP tool: {name}"}
    try:
        validate_tool_call(name, call_args)
    except PermissionError as exc:
        return flow_error_response(name, exc)
    return tool(call_args)
