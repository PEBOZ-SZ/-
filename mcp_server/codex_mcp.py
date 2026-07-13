from __future__ import annotations

import importlib.util
import types
import sys
from pathlib import Path
from typing import Any, Callable, get_args, get_origin


def _patch_pydantic_settings_for_local_sdk() -> None:
    """Work around a local pydantic-settings wheel with missing private exports."""
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
    module.get_args = getattr(module, "get_args", get_args)
    module.get_origin = getattr(module, "get_origin", get_origin)

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

from mcp_server.tools.price_lookup import price_lookup as _price_lookup
from mcp_server.tools.quote_admin import quote_admin as _quote_admin
from mcp_server.tools.quote_approval_status import quote_approval_status as _quote_approval_status
from mcp_server.tools.quote_archive import quote_archive as _quote_archive
from mcp_server.tools.quote_calculate import quote_calculate as _quote_calculate
from mcp_server.tools.quote_explain import quote_explain as _quote_explain
from mcp_server.tools.quote_export import quote_export as _quote_export
from mcp_server.tools.quote_export_pdf import quote_export_pdf as _quote_export_pdf
from mcp_server.tools.quote_get_detail import quote_get_detail as _quote_get_detail
from mcp_server.tools.quote_get_history import quote_get_history as _quote_get_history
from mcp_server.tools.quote_patch_preview import quote_patch_preview as _quote_patch_preview
from mcp_server.tools.quote_qa import quote_qa as _quote_qa
from mcp_server.tools.quote_save import quote_save as _quote_save
from mcp_server.tools.quote_sheet_preview import quote_sheet_preview as _quote_sheet_preview


SERVER_NAME = "mcp-quote-system"
SERVER_VERSION = "0.1.0"

TOOL_REGISTRY: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "quote_calculate": _quote_calculate,
    "price_lookup": _price_lookup,
    "quote_qa": _quote_qa,
    "quote_explain": _quote_explain,
    "quote_patch_preview": _quote_patch_preview,
    "quote_save": _quote_save,
    "quote_export": _quote_export,
    "quote_export_pdf": _quote_export_pdf,
    "quote_approval_status": _quote_approval_status,
    "quote_archive": _quote_archive,
    "quote_get_history": _quote_get_history,
    "quote_get_detail": _quote_get_detail,
    "quote_sheet_preview": _quote_sheet_preview,
    "quote_admin": _quote_admin,
}

mcp = FastMCP(SERVER_NAME, log_level="ERROR")


def _ensure_input(input_data: dict[str, Any] | None) -> dict[str, Any]:
    if input_data is None:
        return {}
    if not isinstance(input_data, dict):
        raise ValueError("MCP tool input must be a dict.")
    return input_data


def _call_existing_tool(tool_name: str, input_data: dict[str, Any] | None) -> dict[str, Any]:
    return TOOL_REGISTRY[tool_name](_ensure_input(input_data))


@mcp.tool(description="Preview quote calculation by calling the existing quote_calculate tool.")
def quote_calculate(input_data: dict[str, Any] | None = None) -> dict[str, Any]:
    return _call_existing_tool("quote_calculate", input_data)


@mcp.tool(description="Readonly price lookup through the existing price_lookup tool.")
def price_lookup(input_data: dict[str, Any] | None = None) -> dict[str, Any]:
    return _call_existing_tool("price_lookup", input_data)


@mcp.tool(description="Readonly quote knowledge Q&A through the existing quote_qa tool.")
def quote_qa(input_data: dict[str, Any] | None = None) -> dict[str, Any]:
    return _call_existing_tool("quote_qa", input_data)


@mcp.tool(description="Explain an existing quote_result through the existing quote_explain tool.")
def quote_explain(input_data: dict[str, Any] | None = None) -> dict[str, Any]:
    return _call_existing_tool("quote_explain", input_data)


@mcp.tool(description="Readonly patch preview and diff for an existing quote_result.")
def quote_patch_preview(input_data: dict[str, Any] | None = None) -> dict[str, Any]:
    return _call_existing_tool("quote_patch_preview", input_data)


@mcp.tool(description="Save an existing quote_result through the existing quote_save tool.")
def quote_save(input_data: dict[str, Any] | None = None) -> dict[str, Any]:
    return _call_existing_tool("quote_save", input_data)


@mcp.tool(description="Export a saved quote through the existing quote_export tool.")
def quote_export(input_data: dict[str, Any] | None = None) -> dict[str, Any]:
    return _call_existing_tool("quote_export", input_data)


@mcp.tool(description="Export a saved formal quote sheet PDF from original quote storage.")
def quote_export_pdf(input_data: dict[str, Any] | None = None) -> dict[str, Any]:
    return _call_existing_tool("quote_export_pdf", input_data)


@mcp.tool(description="Readonly approval status and admin feedback summary for a saved quote.")
def quote_approval_status(input_data: dict[str, Any] | None = None) -> dict[str, Any]:
    return _call_existing_tool("quote_approval_status", input_data)


@mcp.tool(description="Receive GPT-calculated quote data into backend history without generating a quote sheet.")
def quote_archive(input_data: dict[str, Any] | None = None) -> dict[str, Any]:
    return _call_existing_tool("quote_archive", input_data)


@mcp.tool(description="List saved quote history through the original quote storage.")
def quote_get_history(input_data: dict[str, Any] | None = None) -> dict[str, Any]:
    return _call_existing_tool("quote_get_history", input_data)


@mcp.tool(description="Load one saved quote detail and version data through the original quote storage.")
def quote_get_detail(input_data: dict[str, Any] | None = None) -> dict[str, Any]:
    return _call_existing_tool("quote_get_detail", input_data)


@mcp.tool(
    description=(
        "Build the original system quote-sheet preview/download URL from GPT-prepared product rows "
        "or a saved quote record. Use this for quote-sheet preview or export. If it fails, report the "
        "failure and retry or ask the user to save first; never create a local Excel, PDF, HTML, or "
        "spreadsheet preview as a replacement."
    )
)
def quote_sheet_preview(input_data: dict[str, Any] | None = None) -> dict[str, Any]:
    return _call_existing_tool("quote_sheet_preview", input_data)


@mcp.tool(description="Run quote admin actions through the existing quote_admin tool.")
def quote_admin(input_data: dict[str, Any] | None = None) -> dict[str, Any]:
    return _call_existing_tool("quote_admin", input_data)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
