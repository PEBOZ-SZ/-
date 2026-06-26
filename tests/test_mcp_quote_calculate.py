import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch


class McpQuoteCalculateTests(unittest.TestCase):
    def setUp(self):
        self.audit_path = Path("logs/mcp_audit.jsonl")
        if self.audit_path.exists():
            self.audit_path.unlink()

    def _input(self, role="sales", payload=None):
        return {
            "user_context": {
                "user_id": "sales_001",
                "user_name": "张三",
                "role": role,
                "session_id": "sess_001",
            },
            "payload": payload
            or {
                "product_name": "测试背包",
                "quantities": [300, 500, 1000],
                "items": [{"name": "测试面料", "amount": 10}],
                "mold_fee": 1000,
                "processing_fee": 12,
                "system_overhead": 4,
                "gross_margin_rate": 0.35,
                "include_fob": True,
            },
        }

    def test_sales_with_items_calls_calculator_bridge(self):
        from mcp_server.tools.quote_calculate import quote_calculate

        with patch("quotation_agent.calculator_bridge.run_calculate_quote") as bridge:
            bridge.return_value = {
                "product_name": "测试背包",
                "material_total": 10,
                "debug": "hidden",
            }

            result = quote_calculate(self._input())

        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "preview")
        self.assertEqual(result["result"]["product_name"], "测试背包")
        self.assertNotIn("debug", result["result"])
        bridge.assert_called_once()

    def test_admin_role_can_quote_calculate(self):
        from mcp_server.tools.quote_calculate import quote_calculate

        with patch("quotation_agent.calculator_bridge.run_calculate_quote") as bridge:
            bridge.return_value = {"product_name": "测试背包"}
            result = quote_calculate(self._input(role="admin"))

        self.assertTrue(result["ok"])
        bridge.assert_called_once()

    def test_system_admin_role_can_quote_calculate(self):
        from mcp_server.tools.quote_calculate import quote_calculate

        with patch("quotation_agent.calculator_bridge.run_calculate_quote") as bridge:
            bridge.return_value = {"product_name": "测试背包"}
            result = quote_calculate(self._input(role="system_admin"))

        self.assertTrue(result["ok"])
        bridge.assert_called_once()

    def test_guest_role_returns_permission_error(self):
        from mcp_server.tools.quote_calculate import quote_calculate

        result = quote_calculate(self._input(role="guest"))

        self.assertFalse(result["ok"])
        self.assertIn("无权", result["error"])

    def test_unknown_role_is_treated_as_guest(self):
        from mcp_server.tools.quote_calculate import quote_calculate

        result = quote_calculate(self._input(role="owner"))

        self.assertFalse(result["ok"])
        self.assertIn("无权", result["error"])

    def test_missing_items_returns_validation_error(self):
        from mcp_server.tools.quote_calculate import quote_calculate

        data = self._input(payload={"product_name": "测试背包"})
        result = quote_calculate(data)

        self.assertFalse(result["ok"])
        self.assertIn("缺少明细 items", result["error"])

    def test_call_writes_audit_log(self):
        from mcp_server.tools.quote_calculate import quote_calculate

        with patch("quotation_agent.calculator_bridge.run_calculate_quote") as bridge:
            bridge.return_value = {"product_name": "测试背包", "items": []}
            quote_calculate(self._input())

        self.assertTrue(self.audit_path.exists())
        records = [
            json.loads(line)
            for line in self.audit_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertGreaterEqual(len(records), 1)
        self.assertEqual(records[-1]["tool"], "quote_calculate")
        self.assertEqual(records[-1]["user_id"], "sales_001")
        self.assertEqual(records[-1]["role"], "sales")
        self.assertEqual(records[-1]["items_count"], 1)
        self.assertTrue(records[-1]["success"])


if __name__ == "__main__":
    unittest.main()
