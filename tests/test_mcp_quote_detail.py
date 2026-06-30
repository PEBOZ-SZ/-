import base64
import json
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class McpQuoteDetailTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.audit_path = Path("logs/mcp_audit.jsonl")
        if self.audit_path.exists():
            self.audit_path.unlink()

    def tearDown(self):
        self.tmpdir.cleanup()

    @contextmanager
    def _storage(self):
        import quote_upload_storage as storage

        old_db_path = storage.DB_PATH
        old_data_dir = storage.DATA_DIR
        old_uploads_dir = storage.UPLOADS_DIR
        root = Path(self.tmpdir.name)
        storage.DATA_DIR = root
        storage.UPLOADS_DIR = root / "uploads"
        storage.DB_PATH = root / "quotes.db"
        try:
            yield storage
        finally:
            storage.DB_PATH = old_db_path
            storage.DATA_DIR = old_data_dir
            storage.UPLOADS_DIR = old_uploads_dir

    def _quote_result(self, calc_id, product_name, row_name):
        return {
            "quote_id": calc_id,
            "product_name": product_name,
            "material_total": 10,
            "tiers": [{"quantity": 300, "cost_before_margin": 20}],
            "detail_rows": [
                {
                    "name": row_name,
                    "spec": "600D",
                    "usage": "1m",
                    "unit_price": "10",
                    "amount": 10,
                    "amount_text": "10.00",
                    "source": "uploaded_bom",
                }
            ],
        }

    def _seed(self, storage):
        storage.finalize_quote_persistence(
            quote_series_uid="series-001",
            quote_result=self._quote_result("calc-001-v1", "Alpha Bag v1", "fabric-v1"),
            uploaded_sheet=None,
            sheet_original_display_name="alpha-v1.xlsx",
            sales_user_id="sales-001",
            sales_user_name="寮犱笁",
        )
        storage.finalize_quote_persistence(
            quote_series_uid="series-001",
            quote_result=self._quote_result("calc-001-v2", "Alpha Bag v2", "fabric-v2"),
            uploaded_sheet={
                "name": "alpha-v2.xlsx",
                "content_base64": base64.b64encode(b"sheet").decode("ascii"),
                "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            },
            sheet_original_display_name="alpha-v2.xlsx",
            sales_user_id="sales-001",
            structured_input={"customer_name": "Alpha Co"},
            validation_status="passed",
            source_summary={"source": "upload"},
            sales_user_name="寮犱笁",
        )
        storage.finalize_quote_persistence(
            quote_series_uid="series-002",
            quote_result=self._quote_result("calc-002-v1", "Other Bag", "other-fabric"),
            uploaded_sheet=None,
            sheet_original_display_name="other.xlsx",
            sales_user_id="sales-002",
            sales_user_name="鏉庡洓",
        )
        storage.update_saved_quote_approval(
            "series-001",
            approval_status="rejected",
            approval_note="浠锋牸闇€璋冩暣",
            reviewed_by="admin",
        )
        storage.save_quote_chat_message(
            "series-001",
            "assistant",
            "quote saved",
            message_id="msg-001",
            metadata={"type": "quote"},
        )

    def _input(self, role="sales", sales_user_id="sales-001", query=None):
        return {
            "user_context": {
                "user_id": "u-001",
                "role": role,
                "session_id": "sess-001",
                "sales_user_id": sales_user_id,
                "sales_user_name": "寮犱笁",
            },
            "query": query if query is not None else {"quote_uid": "series-001"},
        }

    def test_quote_uid_or_calc_quote_id_is_required(self):
        from mcp_server.tools.quote_get_detail import quote_get_detail

        result = quote_get_detail(self._input(query={}))

        self.assertFalse(result["ok"])
        self.assertIn("quote_uid", result["error"])

    def test_sales_user_id_required_for_sales(self):
        from mcp_server.tools.quote_get_detail import quote_get_detail

        with self._storage() as storage:
            self._seed(storage)
            result = quote_get_detail(self._input(sales_user_id=""))

        self.assertFalse(result["ok"])
        self.assertIn("sales_user_id", result["error"])

    def test_sales_can_view_own_latest_detail(self):
        from mcp_server.tools.quote_get_detail import quote_get_detail

        with self._storage() as storage:
            self._seed(storage)
            result = quote_get_detail(
                self._input(query={"quote_uid": "series-001", "include_files": True})
            )

        self.assertTrue(result["ok"])
        detail = result["result"]
        self.assertEqual(detail["quote_uid"], "series-001")
        self.assertEqual(detail["calc_quote_id"], "calc-001-v2")
        self.assertEqual(detail["version_no"], 2)
        self.assertEqual(detail["quote_result"]["product_name"], "Alpha Bag v2")
        self.assertEqual(detail["detail_rows"][0]["name"], "fabric-v2")
        self.assertEqual(detail["approval_status"], "rejected")
        self.assertEqual(detail["approval_note"], "浠锋牸闇€璋冩暣")
        self.assertEqual(detail["files"][0]["original_name"], "alpha-v2.xlsx")
        self.assertIn("admin_feedback", detail)

    def test_sales_cannot_view_other_quote_uses_safe_error(self):
        from mcp_server.tools.quote_get_detail import quote_get_detail

        with self._storage() as storage:
            self._seed(storage)
            result = quote_get_detail(self._input(query={"quote_uid": "series-002"}))

        self.assertFalse(result["ok"])
        self.assertIn("不存在或无权", result["error"])
        self.assertNotIn("series-002", result["error"])

    def test_admin_and_system_admin_can_view_any_quote(self):
        from mcp_server.tools.quote_get_detail import quote_get_detail

        with self._storage() as storage:
            self._seed(storage)
            admin = quote_get_detail(
                self._input(role="admin", sales_user_id="", query={"quote_uid": "series-002"})
            )
            system_admin = quote_get_detail(
                self._input(role="system_admin", sales_user_id="", query={"quote_uid": "series-002"})
            )

        self.assertTrue(admin["ok"])
        self.assertTrue(system_admin["ok"])
        self.assertEqual(admin["result"]["sales_user_id"], "sales-002")
        self.assertEqual(system_admin["result"]["sales_user_id"], "sales-002")

    def test_version_no_and_calc_quote_id_targeting(self):
        from mcp_server.tools.quote_get_detail import quote_get_detail

        with self._storage() as storage:
            self._seed(storage)
            version_one = quote_get_detail(
                self._input(query={"quote_uid": "series-001", "version_no": 1})
            )
            by_calc = quote_get_detail(
                self._input(query={"calc_quote_id": "calc-001-v1"})
            )

        self.assertEqual(version_one["result"]["version_no"], 1)
        self.assertEqual(version_one["result"]["quote_result"]["product_name"], "Alpha Bag v1")
        self.assertEqual(by_calc["result"]["quote_uid"], "series-001")
        self.assertEqual(by_calc["result"]["version_no"], 1)

    def test_version_id_targeting_and_existing_version_metadata(self):
        from mcp_server.tools.quote_get_detail import quote_get_detail

        with self._storage() as storage:
            self._seed(storage)
            latest = quote_get_detail(self._input(query={"quote_uid": "series-001"}))
            version_id = latest["result"]["version_id"]
            by_version_id = quote_get_detail(
                self._input(query={"quote_uid": "series-001", "version_id": version_id})
            )

        self.assertEqual(by_version_id["result"]["version_id"], version_id)
        self.assertEqual(by_version_id["result"]["version_no"], 2)
        self.assertEqual(by_version_id["result"]["structured_input"], {"customer_name": "Alpha Co"})
        self.assertEqual(by_version_id["result"]["source_summary"], {"source": "upload"})
        self.assertEqual(by_version_id["result"]["validation_status"], "passed")

    def test_include_files_and_chat_messages_flags(self):
        from mcp_server.tools.quote_get_detail import quote_get_detail

        with self._storage() as storage:
            self._seed(storage)
            default_result = quote_get_detail(self._input(query={"quote_uid": "series-001"}))
            no_files = quote_get_detail(
                self._input(query={"quote_uid": "series-001", "include_files": False})
            )
            with_chat = quote_get_detail(
                self._input(
                    query={
                        "quote_uid": "series-001",
                        "include_files": False,
                        "include_chat_messages": True,
                    }
                )
            )

        self.assertNotIn("chat_messages", default_result["result"])
        self.assertEqual(no_files["result"].get("files", []), [])
        message_ids = {msg["message_id"] for msg in with_chat["result"]["chat_messages"]}
        self.assertIn("msg-001", message_ids)

    def test_missing_quote_uses_safe_error_and_does_not_recalculate_or_read_jsonl(self):
        from mcp_server.tools.quote_get_detail import quote_get_detail

        with self._storage() as storage, patch("quote_engine.calculate_quote") as engine, patch(
            "quotation_agent.calculator_bridge.run_calculate_quote"
        ) as bridge, patch("pathlib.Path.read_text") as read_text:
            self._seed(storage)
            result = quote_get_detail(
                self._input(role="admin", sales_user_id="", query={"quote_uid": "missing"})
            )

        self.assertFalse(result["ok"])
        self.assertIn("不存在或无权", result["error"])
        engine.assert_not_called()
        bridge.assert_not_called()
        read_text.assert_not_called()

    def test_audit_log_records_summary_without_detail_payloads(self):
        from mcp_server.tools.quote_get_detail import quote_get_detail

        with self._storage() as storage:
            self._seed(storage)
            result = quote_get_detail(self._input(query={"quote_uid": "series-001"}))

        self.assertTrue(result["ok"])
        records = [
            json.loads(line)
            for line in self.audit_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        latest = records[-1]
        self.assertEqual(latest["tool"], "quote_get_detail")
        self.assertEqual(latest["quote_uid"], "series-001")
        self.assertEqual(latest["version_no"], 2)
        self.assertNotIn("quote_result", json.dumps(latest, ensure_ascii=False))
        self.assertNotIn("detail_rows", json.dumps(latest, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
