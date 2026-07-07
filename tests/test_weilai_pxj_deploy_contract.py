from __future__ import annotations

from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class WeilaiPxjDeployContractTests(unittest.TestCase):
    def test_gpt_action_schema_uses_public_quote_domain(self) -> None:
        schema = (PROJECT_ROOT / "docs" / "gpt_action_openapi.yaml").read_text(encoding="utf-8")

        self.assertIn("url: https://weilai-pxj.com", schema)
        self.assertIn("/gpt/quote-agent", schema)
        self.assertIn("operationId: quoteAgent", schema)
        self.assertIn("bearerAuth", schema)

    def test_public_mcp_exposes_only_safe_tools(self) -> None:
        from mcp_server.public_mcp import PUBLIC_TOOL_REGISTRY

        self.assertEqual(
            set(PUBLIC_TOOL_REGISTRY),
            {
                "quote_history",
                "quote_get_detail",
                "quote_sheet_preview",
                "quote_approval_status",
            },
        )
        forbidden = {
            "approve",
            "reject",
            "quote_admin",
            "delete",
            "price_admin_write",
            "raw_database_query",
        }
        joined = " ".join(PUBLIC_TOOL_REGISTRY).lower()
        for name in forbidden:
            self.assertNotIn(name, joined)

    def test_deploy_doc_contains_dns_env_gpt_mcp_and_curl_steps(self) -> None:
        doc = (PROJECT_ROOT / "docs" / "weilai_pxj_gpt_mcp_deploy.md").read_text(encoding="utf-8")

        for expected in (
            "weilai-pxj.com",
            "159.75.112.178",
            "| A | `@` | `159.75.112.178` |",
            "QUOTE_SERVER_HOST=0.0.0.0",
            "QUOTE_SERVER_PORT=8776",
            "GPT_ACTION_TOKEN",
            "KIMI_BASE_URL=https://api.moonshot.cn/v1",
            "POST https://weilai-pxj.com/gpt/quote-agent",
            "https://weilai-pxj.com/mcp",
            "quote_calculate",
            "quote_save",
        ):
            self.assertIn(expected, doc)


if __name__ == "__main__":
    unittest.main()

