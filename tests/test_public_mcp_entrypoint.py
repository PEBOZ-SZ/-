from pathlib import Path


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
