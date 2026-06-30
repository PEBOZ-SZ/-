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


class McpQuoteHistoryTests(unittest.TestCase):
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

    def _quote_result(self, calc_id, product_name, total=10.0):
        return {
            "quote_id": calc_id,
            "product_name": product_name,
            "material_total": total,
            "tiers": [{"quantity": 300, "cost_before_margin": total + 5}],
            "detail_rows": [
                {
                    "name": "fabric",
                    "spec": "600D",
                    "usage": "1m",
                    "unit_price": "10",
                    "amount": total,
                    "amount_text": f"{total:.2f}",
                    "source": "uploaded_bom",
                }
            ],
        }

    def _seed(self, storage):
        storage.finalize_quote_persistence(
            quote_series_uid="series-sales-1",
            quote_result=self._quote_result("calc-sales-1-v1", "Alpha Bag", 10),
            uploaded_sheet=None,
            sheet_original_display_name="alpha-v1.xlsx",
            sales_user_id="sales-001",
            sales_user_name="张三",
        )
        storage.finalize_quote_persistence(
            quote_series_uid="series-sales-1",
            quote_result=self._quote_result("calc-sales-1-v2", "Alpha Bag", 12),
            uploaded_sheet=None,
            sheet_original_display_name="alpha-v2.xlsx",
            sales_user_id="sales-001",
            sales_user_name="张三",
        )
        storage.finalize_quote_persistence(
            quote_series_uid="series-sales-2",
            quote_result=self._quote_result("calc-sales-2-v1", "Beta Tote", 20),
            uploaded_sheet={
                "name": "beta.xlsx",
                "content_base64": base64.b64encode(b"sheet").decode("ascii"),
                "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            },
            sheet_original_display_name="beta.xlsx",
            sales_user_id="sales-002",
            sales_user_name="李四",
        )
        storage.update_saved_quote_approval(
            "series-sales-2",
            approval_status="approved",
            approval_note="ok",
            reviewed_by="admin",
        )

    def _input(self, role="sales", sales_user_id="sales-001", query=None):
        return {
            "user_context": {
                "user_id": "u-001",
                "role": role,
                "session_id": "sess-001",
                "sales_user_id": sales_user_id,
                "sales_user_name": "张三",
            },
            "query": query if query is not None else {"limit": 20, "offset": 0},
        }

    def test_sales_user_id_required_for_sales(self):
        from mcp_server.tools.quote_get_history import quote_get_history

        with self._storage() as storage:
            self._seed(storage)
            result = quote_get_history(self._input(sales_user_id=""))

        self.assertFalse(result["ok"])
        self.assertIn("sales_user_id", result["error"])

    def test_sales_only_sees_own_quotes(self):
        from mcp_server.tools.quote_get_history import quote_get_history

        with self._storage() as storage:
            self._seed(storage)
            result = quote_get_history(self._input())

        self.assertTrue(result["ok"])
        items = result["result"]["items"]
        self.assertEqual(result["result"]["count"], 1)
        self.assertEqual(items[0]["quote_uid"], "series-sales-1")
        self.assertEqual(items[0]["latest_calc_quote_id"], "calc-sales-1-v2")
        self.assertEqual(items[0]["latest_version_no"], 2)
        self.assertEqual(items[0]["approval_status"], "pending")

    def test_admin_and_system_admin_can_see_all_quotes(self):
        from mcp_server.tools.quote_get_history import quote_get_history

        with self._storage() as storage:
            self._seed(storage)
            admin = quote_get_history(self._input(role="admin", sales_user_id=""))
            system_admin = quote_get_history(self._input(role="system_admin", sales_user_id=""))

        self.assertTrue(admin["ok"])
        self.assertTrue(system_admin["ok"])
        self.assertEqual(admin["result"]["count"], 2)
        self.assertEqual(system_admin["result"]["count"], 2)

    def test_filters_keyword_approval_status_and_paginates(self):
        from mcp_server.tools.quote_get_history import quote_get_history

        with self._storage() as storage:
            self._seed(storage)
            by_product = quote_get_history(
                self._input(role="admin", sales_user_id="", query={"keyword": "Beta"})
            )
            by_uid = quote_get_history(
                self._input(role="admin", sales_user_id="", query={"keyword": "series-sales-1"})
            )
            by_calc = quote_get_history(
                self._input(role="admin", sales_user_id="", query={"keyword": "calc-sales-2-v1"})
            )
            approved = quote_get_history(
                self._input(role="admin", sales_user_id="", query={"approval_status": "approved"})
            )
            page = quote_get_history(
                self._input(role="admin", sales_user_id="", query={"limit": 1, "offset": 1})
            )

        self.assertEqual(by_product["result"]["items"][0]["quote_uid"], "series-sales-2")
        self.assertEqual(by_uid["result"]["items"][0]["quote_uid"], "series-sales-1")
        self.assertEqual(by_calc["result"]["items"][0]["quote_uid"], "series-sales-2")
        self.assertEqual(approved["result"]["items"][0]["approval_status"], "approved")
        self.assertEqual(page["result"]["limit"], 1)
        self.assertEqual(page["result"]["offset"], 1)
        self.assertEqual(page["result"]["count"], 1)

    def test_guest_and_unknown_role_are_denied(self):
        from mcp_server.tools.quote_get_history import quote_get_history

        for role in ("guest", "owner"):
            with self.subTest(role=role), self._storage() as storage:
                self._seed(storage)
                result = quote_get_history(self._input(role=role))
                self.assertFalse(result["ok"])
                self.assertIn("无权", result["error"])

    def test_does_not_read_mcp_saved_quotes_and_audit_has_summary_only(self):
        from mcp_server.tools.quote_get_history import quote_get_history

        with self._storage() as storage, patch("pathlib.Path.read_text") as read_text:
            self._seed(storage)
            result = quote_get_history(self._input())

        self.assertTrue(result["ok"])
        read_text.assert_not_called()
        records = [
            json.loads(line)
            for line in self.audit_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        latest = records[-1]
        self.assertEqual(latest["tool"], "quote_get_history")
        self.assertEqual(latest["count"], 1)
        self.assertNotIn("quote_json", json.dumps(latest, ensure_ascii=False))
        self.assertNotIn("detail_rows", json.dumps(latest, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
