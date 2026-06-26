from __future__ import annotations

from typing import Any

import mcp_router


MCP_TOOL_MAP = mcp_router.TOOL_REGISTRY


def call_mcp_tool(tool_name: str, input_data: dict[str, Any]) -> dict:
    return mcp_router.mcp_call(tool_name, input_data)
