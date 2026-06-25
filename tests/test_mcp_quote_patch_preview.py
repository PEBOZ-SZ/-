import json
import unittest
from pathlib import Path
from unittest.mock import patch


class McpQuotePatchPreviewTests(unittest.TestCase):
    def setUp(self):
        self.audit_path = Path("logs/mcp_audit.jsonl")
        if self.audit_path.exists():
            self.audit_path.unlink()

    def _quote_result(self):
        return {
            "product_name": "测试背包",
            "material_total": 100,
            "tiers": [
                {
                    "quantity": 300,
                    "processing_fee": 12,
                    "cost_before_margin": 55.2,
                    "exw_price": 84.9,
                    "fob_price": 88.9,
                },
                {
                    "quantity": 1000,
                    "processing_fee": 12,
                    "cost_before_margin": 48.6,
                    "exw_price": 74.8,
                    "fob_price": 78.8,
                },
            ],
            "items": [
                {
                    "name": "主料",
                    "spec": "420D",
                    "usage": "1码",
                    "unit_price": "10元/码",
                    "amount": 10,
                }
            ],
        }

    def _input(self, role="sales", patch_data=None, quote_result=None):
        return {
            "user_context": {
                "user_id": "sales_001",
                "role": role,
                "session_id": "sess_001",
            },
            "query": {
                "quote_result": quote_result if quote_result is not None else self._quote_result(),
                "patch": patch_data if patch_data is not None else {"quantity": 1000},
            },
        }

    def test_quantity_patch_selects_matching_tier(self):
        from mcp_server.tools.quote_patch_preview import apply_patch, quote_patch_preview

        result = quote_patch_preview(self._input(patch_data={"quantity": 1000}))

        self.assertTrue(result["ok"])
        self.assertEqual(result["tool"], "quote_patch_preview")
        self.assertEqual(result["mode"], "readonly")
        self.assertEqual(result["result"]["patched_quote"]["selected_tier"]["quantity"], 1000)
        self.assertIn("quantity", result["result"]["diff"]["changed_fields"])
        direct = apply_patch(self._quote_result(), {"quantity": 1000})
        self.assertEqual(direct["selected_tier"]["quantity"], 1000)

    def test_processing_fee_patch_updates_existing_tier_values(self):
        from mcp_server.tools.quote_patch_preview import quote_patch_preview

        result = quote_patch_preview(self._input(patch_data={"processing_fee_delta": 0.5}))

        self.assertTrue(result["ok"])
        first_tier = result["result"]["patched_quote"]["tiers"][0]
        self.assertEqual(first_tier["processing_fee"], 12.5)
        self.assertEqual(first_tier["cost_before_margin"], 55.7)
        self.assertEqual(first_tier["exw_price"], 85.4)
        self.assertIn("processing_fee", result["result"]["diff"]["changed_fields"])

    def test_empty_patch_returns_original_quote_result(self):
        from mcp_server.tools.quote_patch_preview import quote_patch_preview

        quote_result = self._quote_result()
        result = quote_patch_preview(self._input(patch_data={}, quote_result=quote_result))

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["patched_quote"], quote_result)
        self.assertEqual(result["result"]["diff"]["changed_fields"], [])
        self.assertEqual(result["result"]["diff"]["delta"], 0)

    def test_guest_role_returns_permission_error(self):
        from mcp_server.tools.quote_patch_preview import quote_patch_preview

        result = quote_patch_preview(self._input(role="guest"))

        self.assertFalse(result["ok"])
        self.assertIn("无权", result["error"])

    def test_does_not_call_quote_engine_or_calculator_bridge(self):
        from mcp_server.tools.quote_patch_preview import quote_patch_preview

        with patch("quote_engine.calculate_quote") as engine, patch(
            "quotation_agent.calculator_bridge.run_calculate_quote"
        ) as bridge:
            result = quote_patch_preview(self._input(patch_data={"quantity": 1000}))

        self.assertTrue(result["ok"])
        engine.assert_not_called()
        bridge.assert_not_called()

    def test_diff_contains_totals_and_delta(self):
        from mcp_server.tools.quote_patch_preview import generate_diff, quote_patch_preview

        result = quote_patch_preview(self._input(patch_data={"processing_fee": 13}))

        diff = result["result"]["diff"]
        self.assertEqual(diff["before_total"], 84.9)
        self.assertEqual(diff["after_total"], 85.9)
        self.assertEqual(diff["delta"], 1.0)
        self.assertAlmostEqual(diff["delta_percent"], 1.18)
        direct = generate_diff(self._quote_result(), result["result"]["patched_quote"])
        self.assertEqual(direct["before_total"], 84.9)
        self.assertEqual(direct["after_total"], 85.9)

    def test_material_replace_marks_preview_material(self):
        from mcp_server.tools.quote_patch_preview import quote_patch_preview

        result = quote_patch_preview(self._input(patch_data={"material_replace": "600D"}))

        self.assertTrue(result["ok"])
        patched = result["result"]["patched_quote"]
        self.assertEqual(patched["preview_material_replace"], "600D")
        self.assertEqual(patched["items"][0]["preview_material_replace"], "600D")
        self.assertIn("material_replace", result["result"]["diff"]["changed_fields"])

    def test_call_writes_audit_log_without_quote_result(self):
        from mcp_server.tools.quote_patch_preview import quote_patch_preview

        quote_patch_preview(self._input(patch_data={"quantity": 1000}))

        self.assertTrue(self.audit_path.exists())
        records = [
            json.loads(line)
            for line in self.audit_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        latest = records[-1]
        self.assertEqual(latest["tool"], "quote_patch_preview")
        self.assertEqual(latest["role"], "sales")
        self.assertEqual(latest["patch_keys"], ["quantity"])
        self.assertTrue(latest["success"])
        self.assertIn("timestamp", latest)
        serialized = json.dumps(latest, ensure_ascii=False)
        self.assertNotIn("quote_result", serialized)
        self.assertNotIn("测试背包", serialized)


if __name__ == "__main__":
    unittest.main()
