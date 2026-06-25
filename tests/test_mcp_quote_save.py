import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class McpQuoteSaveTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.store_path = Path(self.tmpdir.name) / "mcp_saved_quotes.jsonl"
        self.audit_path = Path("logs/mcp_audit.jsonl")
        if self.audit_path.exists():
            self.audit_path.unlink()

    def tearDown(self):
        self.tmpdir.cleanup()

    def _quote_result(self, total=88.9):
        return {
            "product_name": "测试背包",
            "tiers": [{"quantity": 300, "exw_price": total}],
            "total_price": total,
        }

    def _input(self, role="sales", quote_result=None):
        return {
            "user_context": {
                "user_id": "sales_001",
                "role": role,
                "session_id": "sess_001",
            },
            "query": {
                "quote_result": quote_result if quote_result is not None else self._quote_result(),
            },
        }

    def _with_store(self):
        return patch("mcp_server.tools.quote_save.QUOTE_SAVE_STORE_PATH", self.store_path)

    def test_sales_save_success(self):
        from mcp_server.tools.quote_save import quote_save

        with self._with_store():
            result = quote_save(self._input())

        self.assertTrue(result["ok"])
        self.assertEqual(result["tool"], "quote_save")
        self.assertEqual(result["result"]["status"], "saved")
        self.assertTrue(result["result"]["locked"])
        self.assertRegex(result["result"]["quote_id"], r"^Q-\d{8}-\d{4}$")
        self.assertTrue(result["result"]["created_at"])

    def test_guest_role_returns_permission_error(self):
        from mcp_server.tools.quote_save import quote_save

        with self._with_store():
            result = quote_save(self._input(role="guest"))

        self.assertFalse(result["ok"])
        self.assertIn("无权调用 quote_save", result["error"])

    def test_quote_id_is_unique_and_incremental(self):
        from mcp_server.tools.quote_save import quote_save

        with self._with_store():
            first = quote_save(self._input(quote_result=self._quote_result(88.9)))
            second = quote_save(self._input(quote_result=self._quote_result(99.9)))

        self.assertNotEqual(first["result"]["quote_id"], second["result"]["quote_id"])
        self.assertTrue(first["result"]["quote_id"].endswith("-0001"))
        self.assertTrue(second["result"]["quote_id"].endswith("-0002"))

    def test_locked_state_is_written_to_store(self):
        from mcp_server.tools.quote_save import quote_save

        with self._with_store():
            result = quote_save(self._input())

        records = [
            json.loads(line)
            for line in self.store_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(records[-1]["quote_id"], result["result"]["quote_id"])
        self.assertTrue(records[-1]["locked"])
        self.assertTrue(records[-1]["quote_result"]["locked"])

    def test_does_not_call_quote_engine(self):
        from mcp_server.tools.quote_save import quote_save

        with self._with_store(), patch("quote_engine.calculate_quote") as engine, patch(
            "quotation_agent.calculator_bridge.run_calculate_quote"
        ) as bridge:
            result = quote_save(self._input())

        self.assertTrue(result["ok"])
        engine.assert_not_called()
        bridge.assert_not_called()

    def test_data_is_written_to_storage_layer(self):
        from mcp_server.tools.quote_save import quote_save

        with self._with_store():
            result = quote_save(self._input())

        self.assertTrue(self.store_path.exists())
        records = [
            json.loads(line)
            for line in self.store_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        latest = records[-1]
        self.assertEqual(latest["quote_id"], result["result"]["quote_id"])
        self.assertEqual(latest["user_id"], "sales_001")
        self.assertEqual(latest["quote_result"]["product_name"], "测试背包")

    def test_audit_log_records_summary_without_quote_result(self):
        from mcp_server.tools.quote_save import quote_save

        with self._with_store():
            result = quote_save(self._input())

        records = [
            json.loads(line)
            for line in self.audit_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        latest = records[-1]
        self.assertEqual(latest["tool"], "quote_save")
        self.assertEqual(latest["quote_id"], result["result"]["quote_id"])
        self.assertEqual(latest["total_price"], 88.9)
        self.assertTrue(latest["success"])
        self.assertIn("timestamp", latest)
        self.assertNotIn("quote_result", json.dumps(latest, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
