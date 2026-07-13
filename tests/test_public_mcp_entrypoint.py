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


def test_public_mcp_quote_import_route_receives_gpt_rows(monkeypatch) -> None:
    monkeypatch.setenv("GPT_ACTION_TOKEN", "secret")

    import quote_import_store
    import mcp_server.public_mcp as public_mcp

    captured = {}

    def fake_import_quote_payload(payload, *, sales_user_id=None, sales_user_name=None):
        captured["payload"] = payload
        captured["sales_user_id"] = sales_user_id
        captured["sales_user_name"] = sales_user_name
        return {
            "success": True,
            "quote_id": "gpt-import-public-test",
            "quote_no": payload["quote_no"],
            "quote_uid": payload["quote_no"],
            "version_no": 1,
            "preview_url": "/?view=quoteSheet&quote_uid=GPT-PUBLIC-001",
            "download_url": "/?view=quoteSheet&quote_uid=GPT-PUBLIC-001&exportMode=pdf_rmb",
        }

    monkeypatch.setattr(quote_import_store, "import_quote_payload", fake_import_quote_payload)

    client = TestClient(public_mcp.mcp.streamable_http_app())
    wrong = client.post(
        "/api/quote/import",
        json={"quote_no": "GPT-PUBLIC-001", "products": [{"name": "Lunch Bag"}]},
        headers={"Authorization": "Bearer wrong"},
    )
    ok = client.post(
        "/api/quote/import",
        json={
            "quote_no": "GPT-PUBLIC-001",
            "salesperson": "08",
            "products": [{"name": "Lunch Bag", "qty": 500, "price": 18.6, "total": 9300}],
        },
        headers={"Authorization": "Bearer secret", "Host": "autoquote-mcp.example"},
    )

    assert wrong.status_code == 401
    assert ok.status_code == 200
    body = ok.json()
    assert body["success"] is True
    assert body["quote_uid"] == "GPT-PUBLIC-001"
    assert body["preview_url"] == "http://autoquote-mcp.example/?view=quoteSheet&quote_uid=GPT-PUBLIC-001"
    assert body["download_url"].endswith("exportMode=pdf_rmb")
    assert captured["sales_user_id"] == "08"
    assert captured["sales_user_name"] == "08"
    assert captured["payload"]["products"][0]["name"] == "Lunch Bag"
