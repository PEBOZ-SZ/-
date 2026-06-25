import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class McpQuoteExportTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.store_path = Path(self.tmpdir.name) / "mcp_saved_quotes.jsonl"
        self.export_dir = Path(self.tmpdir.name) / "exports"
        self.audit_path = Path("logs/mcp_audit.jsonl")
        if self.audit_path.exists():
            self.audit_path.unlink()
        self.quote_id = "Q-20260124-0001"
        self._write_saved_quote(self.quote_id)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _quote_result(self):
        return {
            "product_name": "测试背包",
            "quote_id": self.quote_id,
            "locked": True,
            "tiers": [
                {
                    "quantity": 300,
                    "exw_price": 88.9,
                    "fob_price": 92.9,
                    "processing_fee": 12,
                }
            ],
            "items": [
                {
                    "name": "主料",
                    "spec": "600D",
                    "usage": "1码",
                    "unit_price": "10元/码",
                    "amount": 10,
                }
            ],
            "total_price": 88.9,
        }

    def _write_saved_quote(self, quote_id):
        quote_result = self._quote_result()
        quote_result["quote_id"] = quote_id
        record = {
            "quote_id": quote_id,
            "created_at": "2026-01-24T10:00:00",
            "user_id": "sales_001",
            "role": "sales",
            "session_id": "sess_001",
            "locked": True,
            "quote_result": quote_result,
        }
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.store_path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")

    def _input(self, role="sales", quote_id=None):
        return {
            "user_context": {
                "user_id": "sales_001",
                "role": role,
                "session_id": "sess_001",
            },
            "query": {"quote_id": quote_id or self.quote_id},
        }

    def _patch_paths(self):
        return patch.multiple(
            "mcp_server.tools.quote_export",
            QUOTE_SAVE_STORE_PATH=self.store_path,
            QUOTE_EXPORT_DIR=self.export_dir,
        )

    def test_sales_exports_pdf_successfully(self):
        from mcp_server.tools.quote_export import quote_export

        with self._patch_paths():
            result = quote_export(self._input())

        self.assertTrue(result["ok"])
        self.assertEqual(result["tool"], "quote_export")
        self.assertEqual(result["result"]["quote_id"], self.quote_id)
        self.assertEqual(result["result"]["file_type"], "pdf")
        self.assertTrue(Path(result["result"]["file_path"]).exists())
        self.assertTrue(result["result"]["file_name"].endswith(".pdf"))
        self.assertTrue(result["result"]["created_at"])

    def test_guest_role_returns_permission_error(self):
        from mcp_server.tools.quote_export import quote_export

        with self._patch_paths():
            result = quote_export(self._input(role="guest"))

        self.assertFalse(result["ok"])
        self.assertIn("无权调用 quote_export", result["error"])

    def test_missing_quote_id_returns_error(self):
        from mcp_server.tools.quote_export import quote_export

        with self._patch_paths():
            result = quote_export(self._input(quote_id="Q-20990101-9999"))

        self.assertFalse(result["ok"])
        self.assertIn("不存在", result["error"])

    def test_file_path_is_generated_from_quote_id(self):
        from mcp_server.tools.quote_export import quote_export

        with self._patch_paths():
            result = quote_export(self._input())

        self.assertIn(self.quote_id, result["result"]["file_path"])
        self.assertEqual(result["result"]["file_name"], f"报价单_{self.quote_id}.pdf")

    def test_does_not_call_quote_engine(self):
        from mcp_server.tools.quote_export import quote_export

        with self._patch_paths(), patch("quote_engine.calculate_quote") as engine, patch(
            "quotation_agent.calculator_bridge.run_calculate_quote"
        ) as bridge:
            result = quote_export(self._input())

        self.assertTrue(result["ok"])
        engine.assert_not_called()
        bridge.assert_not_called()

    def test_data_comes_from_quote_save_store(self):
        from mcp_server.tools.quote_export import _load_saved_quote, quote_export

        with self._patch_paths():
            saved = _load_saved_quote(self.quote_id)
            result = quote_export(self._input())

        self.assertEqual(saved["quote_result"]["product_name"], "测试背包")
        pdf_bytes = Path(result["result"]["file_path"]).read_bytes()
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    def test_audit_log_records_summary_without_quote_result(self):
        from mcp_server.tools.quote_export import quote_export

        with self._patch_paths():
            quote_export(self._input())

        records = [
            json.loads(line)
            for line in self.audit_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        latest = records[-1]
        self.assertEqual(latest["tool"], "quote_export")
        self.assertEqual(latest["quote_id"], self.quote_id)
        self.assertEqual(latest["file_type"], "pdf")
        self.assertTrue(latest["success"])
        self.assertIn("timestamp", latest)
        self.assertNotIn("quote_result", json.dumps(latest, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
