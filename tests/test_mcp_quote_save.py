import json
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class McpQuoteSaveTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.store_path = Path(self.tmpdir.name) / "mcp_saved_quotes.jsonl"
        self.audit_path = Path("logs/mcp_audit.jsonl")
        if self.audit_path.exists():
            self.audit_path.unlink()

    def tearDown(self):
        self.tmpdir.cleanup()

    def _quote_result(self, quote_id="calc-001", total=88.9):
        return {
            "quote_id": quote_id,
            "quote_series_uid": "series-001",
            "product_name": "测试背包",
            "quote_mode": "production_mode",
            "validation_status": "passed",
            "source_summary": {"mcp": 1},
            "tiers": [{"quantity": 300, "exw_price": total}],
            "detail_rows": [{"name": "fabric", "amount": total}],
            "total_price": total,
        }

    def _input(self, role="sales", quote_result=None):
        return {
            "user_context": {
                "user_id": "sales_001",
                "user_name": "张三",
                "role": role,
                "session_id": "sess_001",
                "sales_user_id": "sales-db-001",
                "sales_user_name": "销售张三",
                "sales_user_code": "S001",
            },
            "query": {
                "quote_result": quote_result if quote_result is not None else self._quote_result(),
                "uploaded_sheet": {"name": "quote.xlsx"},
                "sheet_original_display_name": "quote.xlsx",
                "structured_input": {"items": [{"name": "fabric"}]},
            },
        }

    @contextmanager
    def _patch_storage(self, latest=None, finalize_side_effect=None):
        if latest is None:
            latest = {
                "id": 42,
                "quote_uid": "series-001",
                "version_no": 2,
                "calc_quote_id": "calc-001",
                "validation_status": "passed",
            }
        finalize = Mock(side_effect=finalize_side_effect)
        resolve = Mock(return_value=latest)
        with patch(
            "mcp_server.tools.quote_save.quote_upload_storage.finalize_quote_persistence",
            finalize,
        ), patch(
            "mcp_server.tools.quote_save.quote_upload_storage.resolve_quote_version_target",
            resolve,
        ):
            yield {
                "finalize_quote_persistence": finalize,
                "resolve_quote_version_target": resolve,
            }

    def test_quote_save_calls_original_finalize_persistence(self):
        from mcp_server.tools.quote_save import quote_save, quote_upload_storage

        with self._patch_storage() as mocks:
            result = quote_save(self._input())

        self.assertTrue(result["ok"])
        mocks["finalize_quote_persistence"].assert_called_once()
        kwargs = mocks["finalize_quote_persistence"].call_args.kwargs
        self.assertEqual(kwargs["quote_series_uid"], "series-001")
        self.assertEqual(kwargs["quote_result"]["quote_id"], "calc-001")
        self.assertEqual(kwargs["uploaded_sheet"], {"name": "quote.xlsx"})
        self.assertEqual(kwargs["sheet_original_display_name"], "quote.xlsx")
        self.assertEqual(kwargs["sales_user_id"], "sales-db-001")
        self.assertEqual(kwargs["sales_user_name"], "销售张三")
        self.assertEqual(kwargs["structured_input"], {"items": [{"name": "fabric"}]})
        self.assertEqual(kwargs["quote_mode"], "production_mode")
        self.assertEqual(kwargs["validation_status"], "passed")
        self.assertEqual(kwargs["source_summary"], {"mcp": 1})
        self.assertEqual(result["result"]["quote_uid"], "series-001")
        self.assertEqual(result["result"]["quote_id"], "calc-001")
        self.assertEqual(result["result"]["version_id"], 42)
        self.assertEqual(result["result"]["version_no"], 2)
        self.assertEqual(result["result"]["status"], "passed")

    def test_quote_save_does_not_write_mcp_saved_quotes_as_formal_storage(self):
        from mcp_server.tools.quote_save import quote_save

        with self._patch_storage(), patch(
            "mcp_server.tools.quote_save.QUOTE_SAVE_STORE_PATH", self.store_path
        ):
            result = quote_save(self._input())

        self.assertTrue(result["ok"])
        self.assertFalse(self.store_path.exists())

    def test_sales_admin_and_system_admin_can_save(self):
        from mcp_server.tools.quote_save import quote_save, quote_upload_storage

        for role in ("sales", "admin", "system_admin"):
            with self.subTest(role=role), self._patch_storage():
                result = quote_save(self._input(role=role))
                self.assertTrue(result["ok"])
                quote_upload_storage.finalize_quote_persistence.assert_called_once()

    def test_guest_and_unknown_role_cannot_save(self):
        from mcp_server.tools.quote_save import quote_save, quote_upload_storage

        for role in ("guest", "owner"):
            with self.subTest(role=role), self._patch_storage():
                result = quote_save(self._input(role=role))
                self.assertFalse(result["ok"])
                self.assertIn("quote_save", result["error"])
                quote_upload_storage.finalize_quote_persistence.assert_not_called()

    def test_finalize_error_returns_mcp_failure(self):
        from mcp_server.tools.quote_save import quote_save, quote_upload_storage

        with self._patch_storage(finalize_side_effect=RuntimeError("db unavailable")) as mocks:
            result = quote_save(self._input())

        self.assertFalse(result["ok"])
        self.assertEqual(result["tool"], "quote_save")
        self.assertIn("db unavailable", result["error"])
        mocks["finalize_quote_persistence"].assert_called_once()

    def test_missing_finalize_required_fields_returns_clear_error(self):
        from mcp_server.tools.quote_save import quote_save, quote_upload_storage

        bad_quote = self._quote_result()
        bad_quote.pop("quote_id")
        with self._patch_storage() as mocks:
            result = quote_save(self._input(quote_result=bad_quote))

        self.assertFalse(result["ok"])
        self.assertIn("quote_result.quote_id", result["error"])
        mocks["finalize_quote_persistence"].assert_not_called()

    def test_does_not_call_quote_engine_or_recalculate(self):
        from mcp_server.tools.quote_save import quote_save

        with self._patch_storage(), patch("quote_engine.calculate_quote") as engine, patch(
            "quotation_agent.calculator_bridge.run_calculate_quote"
        ) as bridge:
            result = quote_save(self._input())

        self.assertTrue(result["ok"])
        engine.assert_not_called()
        bridge.assert_not_called()

    def test_audit_log_records_summary_without_quote_result(self):
        from mcp_server.tools.quote_save import quote_save

        with self._patch_storage():
            result = quote_save(self._input())

        records = [
            json.loads(line)
            for line in self.audit_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        latest = records[-1]
        self.assertEqual(latest["tool"], "quote_save")
        self.assertEqual(latest["quote_uid"], result["result"]["quote_uid"])
        self.assertEqual(latest["quote_id"], result["result"]["quote_id"])
        self.assertEqual(latest["version_id"], result["result"]["version_id"])
        self.assertEqual(latest["total_price"], 88.9)
        self.assertTrue(latest["success"])
        self.assertIn("timestamp", latest)
        self.assertNotIn("quote_result", json.dumps(latest, ensure_ascii=False))
        self.assertNotIn("detail_rows", json.dumps(latest, ensure_ascii=False))

    def test_quote_save_persists_into_original_quote_versions(self):
        import quote_upload_storage as storage
        from mcp_server.tools.quote_save import quote_save

        old_db_path = storage.DB_PATH
        old_data_dir = storage.DATA_DIR
        old_uploads_dir = storage.UPLOADS_DIR
        root = Path(self.tmpdir.name)
        storage.DATA_DIR = root
        storage.UPLOADS_DIR = root / "uploads"
        storage.DB_PATH = root / "quotes.db"
        try:
            result = quote_save(self._input())
            latest = storage.resolve_quote_version_target(
                "series-001",
                calc_quote_id="calc-001",
            )
        finally:
            storage.DB_PATH = old_db_path
            storage.DATA_DIR = old_data_dir
            storage.UPLOADS_DIR = old_uploads_dir

        self.assertTrue(result["ok"])
        self.assertEqual(latest["quote_uid"], "series-001")
        self.assertEqual(latest["calc_quote_id"], "calc-001")
        self.assertEqual(latest["version_no"], 1)
        self.assertEqual(latest["structured_input"], {"items": [{"name": "fabric"}]})
        self.assertEqual(latest["source_summary"], {"mcp": 1})


if __name__ == "__main__":
    unittest.main()
