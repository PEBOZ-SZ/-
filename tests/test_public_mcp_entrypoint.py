from pathlib import Path

from starlette.testclient import TestClient


def test_public_mcp_entrypoint_does_not_import_full_codex_mcp() -> None:
    source = Path("mcp_server/public_mcp.py").read_text(encoding="utf-8")

    assert "from mcp_server.codex_mcp import FastMCP" not in source
    assert "from mcp.server.fastmcp import FastMCP" in source
    assert "from server import" not in source


def test_public_mcp_exposes_quote_sheet_payment_account_helpers() -> None:
    import mcp_server.public_mcp as public_mcp

    listing = public_mcp._public_payment_accounts_response()
    assert listing["ok"] is True
    assert "count" in listing

    result = public_mcp._public_payment_accounts_search_response("", limit_raw="30")
    assert result["ok"] is True
    assert "candidates" in result


def test_public_mcp_exposes_readonly_price_lookup_for_gpt() -> None:
    import mcp_server.public_mcp as public_mcp
    from price_kb import reset_price_kb

    reset_price_kb()
    assert "price_lookup" in public_mcp.PUBLIC_TOOL_REGISTRY

    result = public_mcp.PUBLIC_TOOL_REGISTRY["price_lookup"](
        {"query": {"name": "600D牛津布", "spec": "600D", "limit": 3, "min_score": 0.1}}
    )

    assert result["ok"] is True
    hits = result["result"]["hits"]
    assert hits
    assert hits[0]["name"] == "600D牛津布"
    assert hits[0]["price"] == "8元/码"
    assert hits[0]["unit_price_value"] == 8


def test_public_mcp_legacy_quote_history_routes_material_price_query_to_kb() -> None:
    import mcp_server.public_mcp as public_mcp
    from price_kb import reset_price_kb

    reset_price_kb()
    result = public_mcp.quote_history(
        {"query": {"keyword": "请查询知识库价格：600D牛津布，不能AI暂估"}}
    )

    assert result["ok"] is True
    assert result["tool"] == "price_lookup"
    assert result["legacy_tool"] == "quote_history"
    assert "知识库价格" in result["assistant_hint"]
    hits = result["result"]["hits"]
    assert hits
    assert hits[0]["name"] == "600D牛津布"
    assert hits[0]["price"] == "8元/码"


def test_public_mcp_serves_quote_sheet_translate_en_as_json() -> None:
    import mcp_server.public_mcp as public_mcp

    client = TestClient(public_mcp.mcp.streamable_http_app())
    resp = client.post(
        "/api/quote-sheet/translate-en",
        json={
            "bundle": {
                "meta": {"quote_no": "Q-EN-001", "cust_name": "ACME"},
                "rows": [
                    {
                        "line_order": 0,
                        "name": "Lunch Bag",
                        "size": "25x18x20cm",
                        "desc": "600D Oxford",
                        "pack": "1 pc",
                        "qty": "500",
                        "price": "18.6",
                        "total": "9300",
                        "note": "",
                    }
                ],
            }
        },
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is True
    assert payload["rows_en"][0]["name"] == "Lunch Bag"
    assert isinstance(payload["labels"], dict)
    assert isinstance(payload["fixed"], dict)


def test_public_mcp_serves_quote_sheet_validate_export_as_json() -> None:
    import mcp_server.public_mcp as public_mcp

    client = TestClient(public_mcp.mcp.streamable_http_app())
    resp = client.post(
        "/api/quote-sheet/validate-export",
        json={
            "export_lang": "en",
            "bundle": {"payee": {"company_name": "PEBOZ DESIGN LIMITED"}},
        },
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["export_lang"] == "en"
    assert "issues" in payload
