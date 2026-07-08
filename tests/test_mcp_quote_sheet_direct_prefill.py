import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(autouse=True)
def disable_direct_quote_sheet_archive(monkeypatch):
    monkeypatch.setenv("QUOTE_SHEET_DIRECT_ARCHIVE", "0")


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
    assert "quote_sheet_payload=" in payload["preview_url"]
    assert "quote_sheet_token=" in payload["download_url"]
    assert "quote_sheet_payload=" in payload["download_url"]
    assert "exportMode=pdf_rmb" in payload["download_url"]
    assert payload["prefill"]["meta"]["cust_name"] == "ACME"
    assert payload["prefill"]["meta"]["seller_contact"] == "Nina"
    assert payload["prefill"]["rows"][0]["name"] == "Lunch Bag"
    assert payload["prefill"]["rows"][0]["qty"] == "500"
    assert payload["prefill"]["rows"][0]["price"] == "18.6"
    assert payload["prefill"]["rows"][0]["total"] == "9300"


def test_quote_sheet_preview_url_payload_can_refill_after_token_loss(tmp_path, monkeypatch):
    monkeypatch.setenv("QUOTE_SHEET_PUBLIC_DIR", str(tmp_path / "public_quote_sheets"))
    monkeypatch.setenv("PUBLIC_MCP_BASE_URL", "https://autoquote-mcp.example")

    from mcp_server.tools.quote_sheet_preview import quote_sheet_preview
    from quote_sheet_public_store import decode_public_quote_sheet_prefill_payload

    result = quote_sheet_preview(
        {
            "query": {
                "product_name": "Token Backup Bag",
                "quote_sheet_rows": [
                    {
                        "product_name": "Token Backup Bag",
                        "size": "20x10x8cm",
                        "quantity": 300,
                        "unit_price": 11.2,
                    }
                ],
                "include_prefill": True,
            }
        }
    )

    preview_url = result["result"]["preview_url"]
    encoded = preview_url.split("quote_sheet_payload=", 1)[1].split("&", 1)[0]
    decoded = decode_public_quote_sheet_prefill_payload(encoded)

    assert decoded is not None
    assert decoded["ok"] is True
    assert decoded["rows"][0]["name"] == "Token Backup Bag"
    assert decoded["rows"][0]["qty"] == "300"


def test_public_bootstrap_mentions_payload_fallback() -> None:
    source = Path("mcp_server/public_mcp.py").read_text(encoding="utf-8")

    assert "quote_sheet_payload" in source
    assert "decodePayload" in source


def test_quote_sheet_preview_keeps_product_image_for_direct_prefill(tmp_path, monkeypatch):
    monkeypatch.setenv("QUOTE_SHEET_PUBLIC_DIR", str(tmp_path / "public_quote_sheets"))
    monkeypatch.setenv("PUBLIC_MCP_BASE_URL", "https://autoquote-mcp.example")

    from mcp_server.tools.quote_sheet_preview import quote_sheet_preview

    product_image = "data:image/png;base64,PRODUCT_IMAGE"

    result = quote_sheet_preview(
        {
            "query": {
                "product_name": "Lunch Bag",
                "product_image_data_url": product_image,
                "quote_sheet_rows": [
                    {
                        "product_name": "Lunch Bag",
                        "quantity": 100,
                        "unit_price": 9.8,
                    }
                ],
                "include_prefill": True,
            }
        }
    )

    assert result["ok"] is True
    row = result["result"]["prefill"]["rows"][0]
    assert row["image_data_url"] == product_image


def test_quote_sheet_preview_rejects_bom_image_for_direct_prefill(tmp_path, monkeypatch):
    monkeypatch.setenv("QUOTE_SHEET_PUBLIC_DIR", str(tmp_path / "public_quote_sheets"))
    monkeypatch.setenv("PUBLIC_MCP_BASE_URL", "https://autoquote-mcp.example")

    from mcp_server.tools.quote_sheet_preview import quote_sheet_preview

    result = quote_sheet_preview(
        {
            "query": {
                "product_name": "Lunch Bag",
                "image_data_url": "data:image/png;base64,BOM_TABLE",
                "image_role": "bom table screenshot",
                "quote_sheet_rows": [
                    {
                        "product_name": "Lunch Bag",
                        "quantity": 100,
                        "unit_price": 9.8,
                    }
                ],
                "include_prefill": True,
            }
        }
    )

    assert result["ok"] is True
    row = result["result"]["prefill"]["rows"][0]
    assert row["image_data_url"] == ""


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


def test_quote_sheet_preview_accepts_nested_quote_result_without_saved_quote(tmp_path, monkeypatch):
    monkeypatch.setenv("QUOTE_SHEET_PUBLIC_DIR", str(tmp_path / "public_quote_sheets"))
    monkeypatch.setenv("PUBLIC_MCP_BASE_URL", "https://autoquote-mcp.example")

    from mcp_server.tools.quote_sheet_preview import quote_sheet_preview

    result = quote_sheet_preview(
        {
            "quote_result": {
                "product_name": "化妆包",
                "product_size": {"length_cm": 20, "width_cm": 10, "height_cm": 8},
                "customer_description": "PU面料，拉链开口",
                "packaging": "1个/OPP袋",
                "tiers": [{"quantity": 1000, "exw_price": 9.8, "amount": 9800}],
                "items": [{"name": "PU料", "amount": 2.5}],
            },
            "include_prefill": True,
        }
    )

    assert result["ok"] is True
    row = result["result"]["prefill"]["rows"][0]
    assert row["name"] == "化妆包"
    assert row["size"] == "20×10×8cm"
    assert row["pack"] == "1个/OPP袋"
    assert row["qty"] == "1000"
    assert row["price"] == "9.8"
    assert row["total"] == "9800"


def test_quote_sheet_preview_accepts_chinese_quote_summary_without_saved_quote(tmp_path, monkeypatch):
    monkeypatch.setenv("QUOTE_SHEET_PUBLIC_DIR", str(tmp_path / "public_quote_sheets"))
    monkeypatch.setenv("PUBLIC_MCP_BASE_URL", "https://autoquote-mcp.example")

    from mcp_server.tools.quote_sheet_preview import quote_sheet_preview

    result = quote_sheet_preview(
        {
            "query": {
                "产品名称": "篮球包",
                "尺寸": "32×19×45cm",
                "描述": "篮球背包；600D防泼水",
                "包装": "单个OPP袋，纸箱包装",
                "报价汇总": [
                    {
                        "数量": 500,
                        "EXW单价": 76.1,
                        "总价": 38050,
                        "备注": "500个；刀模费1000元按500个摊销。",
                    },
                    {
                        "数量": 1000,
                        "EXW单价": 73,
                        "总价": 73000,
                    },
                ],
                "include_prefill": True,
            }
        }
    )

    assert result["ok"] is True
    payload = result["result"]
    assert payload["prefill_summary"]["rows_count"] == 1
    row = payload["prefill"]["rows"][0]
    assert row["name"] == "篮球包"
    assert row["size"] == "32×19×45cm"
    assert row["desc"] == "篮球背包；600D防泼水"
    assert row["pack"] == "单个OPP袋，纸箱包装"
    assert row["qty"] == "500"
    assert row["price"] == "76.1"
    assert row["total"] == "38050"
    assert row["note"] == ""


def test_quote_sheet_preview_can_archive_direct_prefill(monkeypatch, tmp_path):
    monkeypatch.setenv("QUOTE_SHEET_PUBLIC_DIR", str(tmp_path / "public_quote_sheets"))
    monkeypatch.setenv("PUBLIC_MCP_BASE_URL", "https://autoquote-mcp.example")
    monkeypatch.setenv("QUOTE_SHEET_DIRECT_ARCHIVE", "1")

    import quote_import_store
    from mcp_server.tools.quote_sheet_preview import quote_sheet_preview

    captured = {}

    def fake_import_quote_payload(payload, *, sales_user_id=None, sales_user_name=None):
        captured["payload"] = payload
        captured["sales_user_id"] = sales_user_id
        captured["sales_user_name"] = sales_user_name
        return {
            "success": True,
            "quote_uid": payload["quote_no"],
            "quote_id": "gpt-import-test",
            "version_no": 1,
            "preview_url": "/?view=quoteSheet&quote_uid=test",
        }

    monkeypatch.setattr(quote_import_store, "import_quote_payload", fake_import_quote_payload)

    result = quote_sheet_preview(
        {
            "query": {
                "product_name": "Basketball Bag",
                "archive": True,
                "quote_sheet_rows": [
                    {
                        "product_name": "Basketball Bag",
                        "size": "32x19x45cm",
                        "quantity": 500,
                        "unit_price": 76.1,
                        "amount": 38050,
                    }
                ],
                "include_prefill": True,
            }
        }
    )

    assert result["ok"] is True
    payload = result["result"]
    assert payload["archive"]["saved"] is True
    assert payload["quote_uid"].startswith("GPT-")
    assert payload["calc_quote_id"] == "gpt-import-test"
    assert captured["sales_user_id"] == "gpt_action"
    assert captured["payload"]["products"][0]["name"] == "Basketball Bag"
    assert captured["payload"]["products"][0]["qty"] == "500"
    assert captured["payload"]["products"][0]["price"] == "76.1"
    assert captured["payload"]["products"][0]["total"] == "38050"


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
