from __future__ import annotations

import os
import importlib.util
import sys
import types
from pathlib import Path
from typing import Any, Callable


def _patch_pydantic_settings_for_local_sdk() -> None:
    """Work around local pydantic-settings wheels with missing private exports."""
    package_dir = Path(sys.prefix) / "Lib" / "site-packages" / "pydantic_settings"
    if not package_dir.exists():
        return
    package = types.ModuleType("pydantic_settings")
    package.__file__ = str(package_dir / "__init__.py")
    package.__path__ = [str(package_dir)]
    sys.modules["pydantic_settings"] = package

    if "pydantic_settings.utils" in sys.modules:
        module = sys.modules["pydantic_settings.utils"]
    else:
        utils_path = package_dir / "utils.py"
        spec = importlib.util.spec_from_file_location("pydantic_settings.utils", utils_path)
        if spec is None or spec.loader is None or not utils_path.exists():
            return
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        sys.modules["pydantic_settings.utils"] = module

    from pydantic._internal._utils import lenient_issubclass as _lenient_issubclass

    module._lenient_issubclass = getattr(module, "_lenient_issubclass", _lenient_issubclass)
    module._typing_base = getattr(module, "_typing_base", type(Any))
    module._WithArgsTypes = getattr(module, "_WithArgsTypes", (type(list[int]),))
    module.get_args = getattr(module, "get_args", getattr(__import__("typing"), "get_args"))
    module.get_origin = getattr(module, "get_origin", getattr(__import__("typing"), "get_origin"))

    exceptions_path = package_dir / "exceptions.py"
    exceptions_spec = importlib.util.spec_from_file_location("pydantic_settings.exceptions", exceptions_path)
    if exceptions_spec is None or exceptions_spec.loader is None or not exceptions_path.exists():
        return
    exceptions_module = importlib.util.module_from_spec(exceptions_spec)
    exceptions_spec.loader.exec_module(exceptions_module)
    sys.modules["pydantic_settings.exceptions"] = exceptions_module

    import pydantic_settings.sources as _settings_sources

    _settings_sources.SettingsError = exceptions_module.SettingsError

    main_path = package_dir / "main.py"
    main_spec = importlib.util.spec_from_file_location("pydantic_settings.main", main_path)
    if main_spec is None or main_spec.loader is None or not main_path.exists():
        return
    main_module = importlib.util.module_from_spec(main_spec)
    sys.modules["pydantic_settings.main"] = main_module
    main_spec.loader.exec_module(main_module)

    package.BaseSettings = main_module.BaseSettings
    package.CliApp = main_module.CliApp
    package.SettingsConfigDict = main_module.SettingsConfigDict


_patch_pydantic_settings_for_local_sdk()
from mcp.server.fastmcp import FastMCP
from mcp_server.tools.quote_approval_status import quote_approval_status as _quote_approval_status
from mcp_server.tools.quote_get_detail import quote_get_detail as _quote_get_detail
from mcp_server.tools.quote_get_history import quote_get_history as _quote_get_history
from mcp_server.tools.quote_sheet_preview import quote_sheet_preview as _quote_sheet_preview


SERVER_NAME = "peboz-auto-quote-public"
SERVER_VERSION = "0.1.0"


PUBLIC_TOOL_REGISTRY: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
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
