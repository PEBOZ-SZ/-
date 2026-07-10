from __future__ import annotations

import asyncio
import os
import importlib.util
import re
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
from mcp_server.tools.quote_archive import quote_archive as _quote_archive
from mcp_server.tools.quote_get_detail import quote_get_detail as _quote_get_detail
from mcp_server.tools.quote_get_history import quote_get_history as _quote_get_history
from mcp_server.tools.quote_sheet_preview import quote_sheet_preview as _quote_sheet_preview
from mcp_server.tools.price_lookup import price_lookup as _price_lookup
from quote_sheet_export_validate import validate_quote_sheet_export_payload
from quote_sheet_i18n import (
    get_quote_sheet_terms_public,
    reload_quote_sheet_terms,
    translate_quote_sheet_fields,
)
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
  function decodePayload(raw) {
    var text = String(raw || "").trim();
    if (!text) return null;
    try {
      var normalized = text.replace(/-/g, "+").replace(/_/g, "/");
      while (normalized.length % 4) normalized += "=";
      return JSON.parse(window.atob(normalized));
    } catch (_) {
      return null;
    }
  }
  async function openPublicQuoteSheet() {
    var token = (param("quote_sheet_token") || param("prefill_token") || "").trim();
    var fallbackPayload = decodePayload(param("quote_sheet_payload") || param("prefill_payload") || "");
    if (!token && !fallbackPayload) return;
    var bridge = window.QuoteSheetBridge || null;
    if (!bridge || typeof bridge.applyPrefill !== "function") {
      window.setTimeout(openPublicQuoteSheet, 120);
      return;
    }
    try {
      var payload = fallbackPayload || null;
      if (token) {
        var resp = await window.fetch("/api/public/quote-sheet-prefill/" + encodeURIComponent(token));
        var fetched = await resp.json().catch(function () { return {}; });
        if (resp.ok && fetched && fetched.ok !== false) {
          payload = fetched;
        } else if (!payload) {
          throw new Error(fetched.message || fetched.error || "quote sheet data not found");
        }
      }
      if (!payload || payload.ok === false) throw new Error("quote sheet data not found");
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
    "quote_archive": _quote_archive,
    "quote_history": _quote_get_history,
    "quote_get_detail": _quote_get_detail,
    "quote_sheet_preview": _quote_sheet_preview,
    "quote_approval_status": _quote_approval_status,
    "price_lookup": _price_lookup,
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


def _public_price_lookup_input(input_data: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(_ensure_input(input_data))
    user_context = payload.get("user_context")
    if not isinstance(user_context, dict) or not str(user_context.get("role") or "").strip():
        payload["user_context"] = {
            "role": "sales",
            "user_id": "gpt_action",
            "user_name": "gpt_action",
            "sales_user_id": "gpt_action",
            "sales_user_name": "gpt_action",
        }
    return payload


def _call_public_price_lookup(input_data: dict[str, Any] | None) -> dict[str, Any]:
    return _price_lookup(_public_price_lookup_input(input_data))


PUBLIC_TOOL_REGISTRY["price_lookup"] = _call_public_price_lookup


def _string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, dict):
        out: list[str] = []
        for item in value.values():
            out.extend(_string_values(item))
        return out
    if isinstance(value, list):
        out = []
        for item in value:
            out.extend(_string_values(item))
        return out
    return []


def _looks_like_material_price_query(text: str) -> bool:
    compact = re.sub(r"\s+", "", text or "")
    if not compact:
        return False
    price_intent = any(word in compact for word in ("知识库", "价格", "单价", "查价", "多少钱", "材料价"))
    material_hint = bool(
        re.search(r"\d+(?:\.\d+)?\s*(?:D|#|MM|CM|M|码|米|寸)", compact, re.IGNORECASE)
        or any(word in compact for word in ("布", "PVC", "PU", "PEVA", "EPE", "拉链", "织带", "D扣", "五金", "纸箱", "胶袋"))
    )
    return material_hint and (price_intent or "历史" not in compact)


def _material_query_from_legacy_history(input_data: dict[str, Any] | None) -> dict[str, Any] | None:
    payload = _ensure_input(input_data)
    query = payload.get("query") if isinstance(payload.get("query"), dict) else {}
    if any(str(query.get(key) or "").strip() for key in ("quote_uid", "calc_quote_id", "quote_id", "version_id")):
        return None

    name = str(
        query.get("name")
        or query.get("material")
        or query.get("material_name")
        or query.get("keyword")
        or payload.get("name")
        or payload.get("material")
        or payload.get("keyword")
        or ""
    ).strip()
    spec = str(query.get("spec") or payload.get("spec") or "").strip()
    text = " ".join(_string_values({"payload": payload, "query": query}))
    candidate = name or text
    if not _looks_like_material_price_query(candidate):
        return None

    material_match = re.search(
        r"([A-Za-z0-9#.\-]*\d+(?:\.\d+)?\s*(?:D|#|MM|CM|M|码|米|寸)\s*[\u4e00-\u9fffA-Za-z0-9#.\-/]{0,24})",
        candidate,
        re.IGNORECASE,
    )
    if material_match:
        name = material_match.group(1)
    for sep in ("查询", "查一下", "查", "看看"):
        if sep in name:
            name = name.split(sep)[-1]
    name = re.split(r"(?:的)?(?:价格|单价|多少钱|查价)", name, maxsplit=1)[0]
    for stop in ("不能AI暂估", "不能暂估", "来源", "必须", "报价", "历史"):
        if stop in name:
            name = name.split(stop, 1)[0]
    for noise in ("请", "调用", "后台", "知识库", "材料"):
        name = name.replace(noise, "")
    name = re.sub(r"[，。！？、:：；;,.!?()\[\]{}<>《》\"'“”‘’]", "", name).strip()
    if not name:
        return None
    if not spec:
        spec_match = re.search(r"\d+(?:\.\d+)?\s*(?:D|#|MM|CM|M|码|米|寸)", name, re.IGNORECASE)
        spec = spec_match.group(0) if spec_match else ""
    return {"query": {"name": name[:80], "spec": spec, "limit": 5, "min_score": 0.1}}


def _call_public_quote_history(input_data: dict[str, Any] | None) -> dict[str, Any]:
    price_query = _material_query_from_legacy_history(input_data)
    if price_query is not None:
        result = _call_public_price_lookup(price_query)
        result["legacy_tool"] = "quote_history"
        result["assistant_hint"] = "这是材料知识库价格查询结果，不是历史报价记录。"
        return result
    return _quote_get_history(_ensure_input(input_data))


PUBLIC_TOOL_REGISTRY["quote_history"] = _call_public_quote_history


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


def _public_quote_sheet_translate_en_response(payload: Any) -> dict[str, Any]:
    bundle = payload.get("bundle") if isinstance(payload, dict) else None
    if not isinstance(bundle, dict):
        return {"ok": False, "error": "invalid_request", "message": "缺少 bundle"}
    translated = translate_quote_sheet_fields(bundle)
    terms = get_quote_sheet_terms_public()
    labels = terms.get("labels") if isinstance(terms.get("labels"), dict) else {}
    fixed = terms.get("fixed") if isinstance(terms.get("fixed"), dict) else {}
    out = dict(translated)
    out["labels"] = labels
    out["fixed"] = fixed
    return out


def _public_quote_sheet_validate_export_response(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"ok": False, "error": "invalid_request", "message": "JSON object required"}
    export_lang = str(payload.get("export_lang") or "cn").strip().lower()
    bundle = payload.get("bundle") if isinstance(payload.get("bundle"), dict) else {}
    return validate_quote_sheet_export_payload(export_lang=export_lang, bundle=bundle)


async def _request_json(request: Request) -> Any:
    try:
        return await request.json()
    except Exception:
        return {}


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


@mcp.custom_route("/api/quote-sheet/translate-en", methods=["POST"], include_in_schema=False)
async def public_quote_sheet_translate_en(request: Request) -> Response:
    payload = await _request_json(request)
    result = _public_quote_sheet_translate_en_response(payload)
    status = 200 if result.get("ok") is not False else 400
    return JSONResponse(result, status_code=status)


@mcp.custom_route("/api/quote-sheet/validate-export", methods=["POST"], include_in_schema=False)
async def public_quote_sheet_validate_export(request: Request) -> Response:
    payload = await _request_json(request)
    result = _public_quote_sheet_validate_export_response(payload)
    status = 200 if result.get("error") != "invalid_request" else 400
    return JSONResponse(result, status_code=status)


@mcp.custom_route("/api/quote-sheet/terms/reload", methods=["POST"], include_in_schema=False)
async def public_quote_sheet_terms_reload(request: Request) -> Response:
    del request
    reload_quote_sheet_terms()
    return JSONResponse(get_quote_sheet_terms_public())


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


@mcp.tool(description="Receive GPT-calculated quote data into backend history without generating a quote sheet.")
def quote_archive(input_data: dict[str, Any] | None = None) -> dict[str, Any]:
    return _call_public_tool("quote_archive", input_data)


@mcp.tool(description="Build a saved quote sheet preview URL and controlled prefill summary.")
def quote_sheet_preview(input_data: dict[str, Any] | None = None) -> dict[str, Any]:
    return _call_public_tool("quote_sheet_preview", input_data)


@mcp.tool(description="Readonly approval status and admin feedback summary for a saved quote.")
def quote_approval_status(input_data: dict[str, Any] | None = None) -> dict[str, Any]:
    return _call_public_tool("quote_approval_status", input_data)


@mcp.tool(description="Readonly material price lookup from the official material knowledge base.")
def price_lookup(input_data: dict[str, Any] | None = None) -> dict[str, Any]:
    return _call_public_price_lookup(input_data)


def main() -> None:
    transport = _public_mcp_transport()
    mount_path = "/sse" if transport == "sse" else None
    mcp.run(transport=transport, mount_path=mount_path)


if __name__ == "__main__":
    main()
