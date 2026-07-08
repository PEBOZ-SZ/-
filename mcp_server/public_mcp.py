from __future__ import annotations

import asyncio
import os
import importlib.util
import sys
import threading
import types
import urllib.error
import urllib.request
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
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from company_payment_accounts import get_company_payment_accounts_public, search_company_accounts
from mcp_server.tools.quote_approval_status import quote_approval_status as _quote_approval_status
from mcp_server.tools.quote_get_detail import quote_get_detail as _quote_get_detail
from mcp_server.tools.quote_get_history import quote_get_history as _quote_get_history
from mcp_server.tools.quote_sheet_preview import quote_sheet_preview as _quote_sheet_preview
from quote_sheet_public_store import load_public_quote_sheet_prefill


SERVER_NAME = "peboz-auto-quote-public"
SERVER_VERSION = "0.1.0"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = PROJECT_ROOT / "static"
_ADMIN_PROXY_LOCK = threading.Lock()
_ADMIN_PROXY_SERVER: Any | None = None
_ADMIN_PROXY_THREAD: threading.Thread | None = None
_ADMIN_PROXY_PORT: int | None = None
_HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
QUOTE_SHEET_TOKEN_BOOTSTRAP = r"""
<script>
(function () {
  function param(name) {
    try {
      return new URLSearchParams(window.location.search || "").get(name) || "";
    } catch (_) {
      return "";
    }
  }
  async function openPublicQuoteSheet() {
    var token = (param("quote_sheet_token") || param("prefill_token") || "").trim();
    if (!token) return;
    var bridge = window.QuoteSheetBridge || null;
    if (!bridge || typeof bridge.applyPrefill !== "function") {
      window.setTimeout(openPublicQuoteSheet, 120);
      return;
    }
    try {
      var resp = await window.fetch("/api/public/quote-sheet-prefill/" + encodeURIComponent(token));
      var payload = await resp.json().catch(function () { return {}; });
      if (!resp.ok || !payload || payload.ok === false) {
        throw new Error(payload.message || payload.error || "quote sheet data not found");
      }
      bridge.applyPrefill(payload);
      var exportMode = (param("exportMode") || param("export_mode") || "").trim();
      if (exportMode === "pdf_rmb" && typeof bridge.exportDirect === "function") {
        await bridge.exportDirect({ fobUsd: false, skipConfirm: true });
      } else if (exportMode === "pdf_fob" && typeof bridge.exportDirect === "function") {
        await bridge.exportDirect({ fobUsd: true, skipConfirm: true });
      }
    } catch (err) {
      window.alert("Load quote sheet failed: " + (err && err.message ? err.message : err));
    }
  }
  window.addEventListener("load", function () {
    window.setTimeout(openPublicQuoteSheet, 120);
  });
})();
</script>
"""


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


def _load_public_quote_sheet_prefill_for_route(token: str) -> dict[str, Any]:
    prefill = load_public_quote_sheet_prefill(token)
    if not isinstance(prefill, dict):
        return {"ok": False, "error": "not_found", "message": "quote sheet prefill token not found"}
    return prefill


def _parse_limit(raw: Any, default: int = 12) -> int:
    try:
        return max(1, min(100, int(str(raw).strip())))
    except (TypeError, ValueError):
        return default


def _public_payment_accounts_response() -> dict[str, Any]:
    return get_company_payment_accounts_public()


def _public_payment_accounts_search_response(
    query: Any,
    *,
    limit_raw: Any = "12",
    account_type: Any = "",
) -> dict[str, Any]:
    return search_company_accounts(
        query,
        limit=_parse_limit(limit_raw),
        account_type=str(account_type or "").strip(),
    )


def _static_response(path: Path) -> Response:
    resolved = path.resolve()
    static_root = STATIC_DIR.resolve()
    if resolved != (STATIC_DIR / "index.html").resolve() and static_root not in resolved.parents:
        return JSONResponse({"ok": False, "error": "invalid_path"}, status_code=403)
    if not resolved.exists() or not resolved.is_file():
        return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
    return FileResponse(resolved)


def _admin_proxy_enabled() -> bool:
    raw = str(os.environ.get("PUBLIC_MCP_ENABLE_ADMIN") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off", "none"}


def _ensure_admin_proxy_server() -> int:
    global _ADMIN_PROXY_PORT, _ADMIN_PROXY_SERVER, _ADMIN_PROXY_THREAD
    if not _admin_proxy_enabled():
        raise RuntimeError("admin proxy is disabled")
    if _ADMIN_PROXY_PORT:
        return int(_ADMIN_PROXY_PORT)
    with _ADMIN_PROXY_LOCK:
        if _ADMIN_PROXY_PORT:
            return int(_ADMIN_PROXY_PORT)

        allow_ips = str(os.environ.get("QUOTE_ADMIN_ALLOW_IPS") or "").strip()
        if allow_ips:
            allowed = {item.strip() for item in allow_ips.split(",") if item.strip()}
            if "127.0.0.1" not in allowed:
                os.environ["QUOTE_ADMIN_ALLOW_IPS"] = f"{allow_ips},127.0.0.1"

        import server as legacy_server

        legacy_server.init_quote_storage()
        httpd = legacy_server.ThreadingHTTPServer(
            ("127.0.0.1", 0),
            legacy_server.QuoteHandler,
        )
        setattr(httpd, "_quote_site", "admin")
        thread = threading.Thread(
            target=httpd.serve_forever,
            daemon=True,
            name="public-mcp-admin-proxy",
        )
        thread.start()
        _ADMIN_PROXY_SERVER = httpd
        _ADMIN_PROXY_THREAD = thread
        _ADMIN_PROXY_PORT = int(httpd.server_address[1])
        return int(_ADMIN_PROXY_PORT)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


def _proxy_request_headers(request: Request) -> dict[str, str]:
    headers: dict[str, str] = {}
    for key, value in request.headers.items():
        low = key.lower()
        if low in _HOP_BY_HOP_HEADERS or low in {"host", "content-length"}:
            continue
        headers[key] = value
    headers["X-Forwarded-Host"] = request.headers.get("host", "")
    headers["X-Forwarded-Proto"] = request.url.scheme
    return headers


def _proxy_response_headers(source: Any) -> dict[str, str]:
    headers: dict[str, str] = {}
    for key in source.keys():
        low = str(key).lower()
        if low in _HOP_BY_HOP_HEADERS or low in {"content-length"}:
            continue
        values = source.get_all(key) if hasattr(source, "get_all") else [source.get(key)]
        if not values:
            continue
        headers[str(key)] = str(values[-1])
    return headers


def _admin_proxy_sync(method: str, path: str, query: str, headers: dict[str, str], body: bytes) -> Response:
    port = _ensure_admin_proxy_server()
    target = f"http://127.0.0.1:{port}{path}"
    if query:
        target = f"{target}?{query}"
    data = body if method.upper() not in {"GET", "HEAD"} else None
    req = urllib.request.Request(target, data=data, headers=headers, method=method.upper())
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=45) as resp:
            payload = resp.read()
            status = int(resp.status)
            resp_headers = _proxy_response_headers(resp.headers)
    except urllib.error.HTTPError as err:
        payload = err.read()
        status = int(err.code)
        resp_headers = _proxy_response_headers(err.headers)
    return Response(content=payload, status_code=status, headers=resp_headers)


async def _admin_proxy(request: Request) -> Response:
    try:
        body = await request.body()
        headers = _proxy_request_headers(request)
        return await asyncio.to_thread(
            _admin_proxy_sync,
            request.method,
            request.url.path,
            request.url.query,
            headers,
            body,
        )
    except Exception as exc:
        return JSONResponse(
            {
                "ok": False,
                "error": "admin_proxy_failed",
                "message": str(exc),
            },
            status_code=502,
        )


def _index_response() -> Response:
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists() or not index_path.is_file():
        return JSONResponse({"ok": False, "error": "not_found"}, status_code=404)
    html = index_path.read_text(encoding="utf-8")
    if "quote_sheet_token" not in html:
        html = html.replace("</body>", f"{QUOTE_SHEET_TOKEN_BOOTSTRAP}\n  </body>")
    return Response(html, media_type="text/html; charset=utf-8")


@mcp.custom_route("/", methods=["GET"], include_in_schema=False)
async def public_index(request: Request) -> Response:
    del request
    return _index_response()


@mcp.custom_route("/index.html", methods=["GET"], include_in_schema=False)
async def public_index_html(request: Request) -> Response:
    del request
    return _index_response()


@mcp.custom_route("/static/{path:path}", methods=["GET"], include_in_schema=False)
async def public_static(request: Request) -> Response:
    rel = str(request.path_params.get("path") or "").lstrip("/")
    return _static_response(STATIC_DIR / rel)


@mcp.custom_route(
    "/admin",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    include_in_schema=False,
)
async def public_admin_root(request: Request) -> Response:
    return await _admin_proxy(request)


@mcp.custom_route(
    "/admin/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    include_in_schema=False,
)
async def public_admin(request: Request) -> Response:
    return await _admin_proxy(request)


@mcp.custom_route(
    "/admin-api",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    include_in_schema=False,
)
async def public_admin_api_root(request: Request) -> Response:
    return await _admin_proxy(request)


@mcp.custom_route(
    "/admin-api/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    include_in_schema=False,
)
async def public_admin_api(request: Request) -> Response:
    return await _admin_proxy(request)


@mcp.custom_route("/api/public/quote-sheet-prefill/{token}", methods=["GET"], include_in_schema=False)
async def public_quote_sheet_prefill(request: Request) -> Response:
    token = str(request.path_params.get("token") or "").strip()
    payload = _load_public_quote_sheet_prefill_for_route(token)
    if not payload.get("ok"):
        return JSONResponse(payload, status_code=404)
    return JSONResponse(payload)


@mcp.custom_route("/api/quote-sheet/payment-accounts", methods=["GET"], include_in_schema=False)
async def public_payment_accounts(request: Request) -> Response:
    del request
    return JSONResponse(_public_payment_accounts_response())


@mcp.custom_route("/api/quote-sheet/payment-accounts/search", methods=["GET"], include_in_schema=False)
async def public_payment_accounts_search(request: Request) -> Response:
    qs = request.query_params
    query = qs.get("q") or qs.get("query") or ""
    limit_raw = qs.get("limit") or "12"
    account_type = qs.get("account_type") or qs.get("type") or ""
    return JSONResponse(
        _public_payment_accounts_search_response(
            query,
            limit_raw=limit_raw,
            account_type=account_type,
        )
    )


@mcp.custom_route("/healthz", methods=["GET"], include_in_schema=False)
async def public_healthz(request: Request) -> Response:
    del request
    return PlainTextResponse("ok")


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
