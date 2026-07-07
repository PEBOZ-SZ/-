from pathlib import Path


def test_public_mcp_entrypoint_does_not_import_full_codex_mcp() -> None:
    source = Path("mcp_server/public_mcp.py").read_text(encoding="utf-8")

    assert "from mcp_server.codex_mcp import FastMCP" not in source
    assert "from mcp.server.fastmcp import FastMCP" in source
