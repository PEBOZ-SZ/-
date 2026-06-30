from __future__ import annotations

import os
from typing import Any, Callable

from mcp_server.codex_mcp import FastMCP
from mcp_server.tools.quote_approval_status import quote_approval_status as _quote_approval_status
from mcp_server.tools.quote_get_detail import quote_get_detail as _quote_get_detail
from mcp_server.tools.quote_get_history import quote_get_history as _quote_get_history
from mcp_server.tools.quote_sheet_preview import quote_sheet_preview as _quote_sheet_preview
from server import handle_quote_agent_request


SERVER_NAME = "peboz-auto-quote-public"
SERVER_VERSION = "0.1.0"


PUBLIC_TOOL_REGISTRY: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "quote_agent": handle_quote_agent_request,
    "quote_history": _quote_get_history,
    "quote_get_detail": _quote_get_detail,
    "quote_sheet_preview": _quote_sheet_preview,
    "quote_approval_status": _quote_approval_status,
}


def _env_int(name: str, default: int) -> int:
    raw = str(os.environ.get(name) or "").strip()
    if raw.isdigit():
        return int(raw)
    return default


def _public_mcp_host() -> str:
    return str(os.environ.get("PUBLIC_MCP_HOST") or "127.0.0.1").strip() or "127.0.0.1"


def _public_mcp_port() -> int:
    return _env_int("PUBLIC_MCP_PORT", 8788)


def _public_mcp_transport() -> str:
    raw = str(os.environ.get("PUBLIC_MCP_TRANSPORT") or "streamable-http").strip().lower()
    return raw if raw in {"stdio", "sse", "streamable-http"} else "streamable-http"


mcp = FastMCP(
    SERVER_NAME,
    log_level="ERROR",
    host=_public_mcp_host(),
    port=_public_mcp_port(),
    streamable_http_path="/mcp",
    sse_path="/sse",
    message_path="/messages/",
)


def _ensure_input(input_data: dict[str, Any] | None) -> dict[str, Any]:
    if input_data is None:
        return {}
    if not isinstance(input_data, dict):
        raise ValueError("MCP tool input must be a dict.")
    return input_data


def _call_public_tool(tool_name: str, input_data: dict[str, Any] | None) -> dict[str, Any]:
    return PUBLIC_TOOL_REGISTRY[tool_name](_ensure_input(input_data))


@mcp.tool(description="Update, recalculate, clarify, or save a quote draft through the safe quote agent.")
def quote_agent(input_data: dict[str, Any] | None = None) -> dict[str, Any]:
    return _call_public_tool("quote_agent", input_data)


@mcp.tool(description="List saved quote history through the original quote storage.")
def quote_history(input_data: dict[str, Any] | None = None) -> dict[str, Any]:
    return _call_public_tool("quote_history", input_data)


@mcp.tool(description="Load one saved quote detail and version data through the original quote storage.")
def quote_get_detail(input_data: dict[str, Any] | None = None) -> dict[str, Any]:
    return _call_public_tool("quote_get_detail", input_data)


@mcp.tool(description="Build a saved quote sheet preview URL and controlled prefill summary.")
def quote_sheet_preview(input_data: dict[str, Any] | None = None) -> dict[str, Any]:
    return _call_public_tool("quote_sheet_preview", input_data)


@mcp.tool(description="Readonly approval status and admin feedback summary for a saved quote.")
def quote_approval_status(input_data: dict[str, Any] | None = None) -> dict[str, Any]:
    return _call_public_tool("quote_approval_status", input_data)


def main() -> None:
    transport = _public_mcp_transport()
    mount_path = "/sse" if transport == "sse" else None
    mcp.run(transport=transport, mount_path=mount_path)


if __name__ == "__main__":
    main()
