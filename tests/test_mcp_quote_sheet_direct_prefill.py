import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def test_quote_sheet_preview_accepts_gpt_prefill_without_saved_quote_or_role(tmp_path, monkeypatch):
    monkeypatch.setenv("QUOTE_SHEET_PUBLIC_DIR", str(tmp_path / "public_quote_sheets"))
    monkeypatch.setenv("PUBLIC_MCP_BASE_URL", "https://autoquote-mcp.example")

    from mcp_server.tools.quote_sheet_preview import quote_sheet_preview

    result = quote_sheet_preview(
        {
            "query": {
                "product_name": "Lunch Bag",
                "meta": {
                    "quote_no": "GPT-Q-001",
                    "customer_name": "ACME",
                    "sales_name": "Nina",
                    "quote_date": "2026-07-07",
                },
                "quote_sheet_rows": [
                    {
                        "product_name": "Lunch Bag",
                        "size": "25x18x20cm",
                        "description": "600D Oxford + PEVA lining",
                        "packaging": "1pc/opp bag",
                        "quantity": 500,
                        "unit_price": 18.6,
                        "amount": 9300,
                        "remark": "GPT calculated",
                    }
                ],
                "include_prefill": True,
                "auto_download": True,
            }
        }
    )

    assert result["ok"] is True
    payload = result["result"]
    assert payload["quote_uid"] == ""
    assert payload["calc_quote_id"] == ""
    assert payload["product_name"] == "Lunch Bag"
    assert payload["prefill_available"] is True
    assert payload["prefill_summary"]["rows_count"] == 1
    assert "quote_sheet_token=" in payload["preview_url"]
    assert "quote_sheet_token=" in payload["download_url"]
    assert "exportMode=pdf_rmb" in payload["download_url"]
    assert payload["prefill"]["meta"]["cust_name"] == "ACME"
    assert payload["prefill"]["meta"]["seller_contact"] == "Nina"
    assert payload["prefill"]["rows"][0]["name"] == "Lunch Bag"
    assert payload["prefill"]["rows"][0]["qty"] == "500"
    assert payload["prefill"]["rows"][0]["price"] == "18.6"
    assert payload["prefill"]["rows"][0]["total"] == "9300"


def test_quote_sheet_preview_accepts_top_level_gpt_prefill_without_user_context(tmp_path, monkeypatch):
    monkeypatch.setenv("QUOTE_SHEET_PUBLIC_DIR", str(tmp_path / "public_quote_sheets"))
    monkeypatch.setenv("PUBLIC_MCP_BASE_URL", "https://autoquote-mcp.example")

    from mcp_server.tools.quote_sheet_preview import quote_sheet_preview

    result = quote_sheet_preview(
        {
            "product_name": "Storage Bag",
            "meta": {"customer_name": "Direct Customer"},
            "quote_sheet_rows": [
                {
                    "product_name": "Storage Bag",
                    "size": "45×30×17 cm",
                    "quantity": 1000,
                    "unit_price": 12.5,
                    "amount": 12500,
                }
            ],
        }
    )

    assert result["ok"] is True
    assert result["result"]["prefill_summary"]["customer_name"] == "Direct Customer"
    assert result["result"]["prefill_summary"]["rows_count"] == 1
    assert "quote_sheet_token=" in result["result"]["preview_url"]


def test_public_mcp_serves_quote_sheet_prefill_tokens_without_quote_agent_import(tmp_path, monkeypatch):
    monkeypatch.setenv("QUOTE_SHEET_PUBLIC_DIR", str(tmp_path / "public_quote_sheets"))

    import mcp_server.public_mcp as public_mcp
    from quote_sheet_public_store import save_public_quote_sheet_prefill

    token = save_public_quote_sheet_prefill(
        {
            "ok": True,
            "source": "gpt_direct",
            "meta": {"cust_name": "ACME"},
            "rows": [{"name": "Lunch Bag", "qty": "500"}],
            "product_name": "Lunch Bag",
        }
    )

    loaded = public_mcp._load_public_quote_sheet_prefill_for_route(token)

    assert loaded["ok"] is True
    assert loaded["rows"][0]["name"] == "Lunch Bag"
    source = Path("mcp_server/public_mcp.py").read_text(encoding="utf-8")
    assert "quote_agent" not in source
