import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def test_quote_archive_saves_gpt_quote_without_creating_quote_sheet(monkeypatch):
    import quote_import_store

    captured = {}

    def fake_import_quote_payload(payload, *, sales_user_id=None, sales_user_name=None):
        captured["payload"] = payload
        captured["sales_user_id"] = sales_user_id
        captured["sales_user_name"] = sales_user_name
        return {
            "success": True,
            "quote_uid": payload["quote_no"],
            "quote_id": "gpt-import-archive-test",
            "version_id": 7,
            "version_no": 1,
            "preview_url": "/?view=quoteSheet&quote_uid=GPT-ARCHIVE-001",
        }

    monkeypatch.setattr(quote_import_store, "import_quote_payload", fake_import_quote_payload)

    from mcp_server.tools.quote_archive import quote_archive

    result = quote_archive(
        {
            "query": {
                "quote_no": "GPT-ARCHIVE-001",
                "product_name": "PVC Bucket",
                "size": "55x70cm",
                "description": "0.5mm PVC bucket",
                "packaging": "1pc/opp bag, carton",
                "summaries": [{"quantity": 500, "exw": 60, "amount": 30000}],
            }
        }
    )

    assert result["ok"] is True
    assert result["tool"] == "quote_archive"
    assert result["result"]["backend_received"] is True
    assert result["result"]["quote_uid"] == "GPT-ARCHIVE-001"
    assert result["result"]["calc_quote_id"] == "gpt-import-archive-test"
    assert "preview_token" not in result["result"]
    assert "download_url" not in result["result"]
    assert captured["sales_user_id"] == "gpt_action"
    assert captured["sales_user_name"] == "GPT"
    assert captured["payload"]["source_file_name"] == "GPT backend archive"
    assert captured["payload"]["products"][0]["name"] == "PVC Bucket"
    assert captured["payload"]["products"][0]["qty"] == "500"
    assert captured["payload"]["products"][0]["price"] == "60"
    assert captured["payload"]["products"][0]["total"] == "30000"


def test_quote_archive_accepts_chinese_gpt_summary(monkeypatch):
    import quote_import_store

    captured = {}

    def fake_import_quote_payload(payload, *, sales_user_id=None, sales_user_name=None):
        captured["payload"] = payload
        return {
            "success": True,
            "quote_uid": payload["quote_no"],
            "quote_id": "gpt-import-cn-test",
            "version_id": 8,
            "version_no": 1,
        }

    monkeypatch.setattr(quote_import_store, "import_quote_payload", fake_import_quote_payload)

    from mcp_server.tools.quote_archive import quote_archive

    result = quote_archive(
        {
            "query": {
                "quote_no": "GPT-ARCHIVE-CN-001",
                "\u4ea7\u54c1\u540d\u79f0": "PVC\u6c34\u6876",
                "\u5c3a\u5bf8": "\u76f4\u5f8455cm\u00d7\u9ad870cm",
                "\u63cf\u8ff0": "0.5mm PVC\u6c34\u6876",
                "\u5305\u88c5": "\u5355\u4e2aOPP\u888b\uff0c\u7eb8\u7bb1\u5305\u88c5",
                "\u62a5\u4ef7\u6c47\u603b": [
                    {"\u6570\u91cf": 500, "EXW\u5355\u4ef7": 60, "\u603b\u4ef7": 30000}
                ],
            }
        }
    )

    assert result["ok"] is True
    assert captured["payload"]["products"][0]["name"] == "PVC\u6c34\u6876"
    assert captured["payload"]["products"][0]["size"] == "\u76f4\u5f8455cm\u00d7\u9ad870cm"
    assert captured["payload"]["products"][0]["qty"] == "500"
    assert captured["payload"]["products"][0]["price"] == "60"
    assert captured["payload"]["products"][0]["total"] == "30000"


def test_quote_sheet_preview_direct_prefill_does_not_archive_by_default(monkeypatch, tmp_path):
    monkeypatch.setenv("QUOTE_SHEET_PUBLIC_DIR", str(tmp_path / "public_quote_sheets"))
    monkeypatch.setenv("PUBLIC_MCP_BASE_URL", "https://autoquote-mcp.example")

    import quote_import_store

    def fail_if_called(*args, **kwargs):
        raise AssertionError("quote_sheet_preview should not archive unless explicitly requested")

    monkeypatch.setattr(quote_import_store, "import_quote_payload", fail_if_called)

    from mcp_server.tools.quote_sheet_preview import quote_sheet_preview

    result = quote_sheet_preview(
        {
            "query": {
                "quote_no": "GPT-PREVIEW-ONLY-001",
                "product_name": "Preview Only Bag",
                "quote_sheet_rows": [
                    {
                        "product_name": "Preview Only Bag",
                        "quantity": 100,
                        "unit_price": 10,
                        "amount": 1000,
                    }
                ],
            }
        }
    )

    assert result["ok"] is True
    assert result["result"]["quote_uid"] == ""
    assert result["result"]["calc_quote_id"] == ""
    assert result["result"]["archive"]["saved"] is False
    assert result["result"]["archive"]["reason"] == "separate_tool_required"
