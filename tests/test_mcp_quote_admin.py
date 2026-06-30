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


class McpQuoteAdminTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.rules_path = Path(self.tmpdir.name) / "mcp_price_rules_admin.jsonl"
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

    def _user_context(self, role="admin", sales_user_id="sales-001"):
        user_id = sales_user_id if role == "sales" else f"{role}-user"
        return {
            "user_id": user_id,
            "user_name": f"{role}-user",
            "role": role,
            "session_id": f"sess-{role}",
            "sales_user_id": sales_user_id if role == "sales" else "",
            "sales_user_name": f"name-{sales_user_id}" if role == "sales" else "",
            "sales_user_code": "S001" if role == "sales" else "",
        }

    def _quote_result(self, calc_id, *, product_name="Admin Approval Bag", amount=10):
        return {
            "quote_id": calc_id,
            "product_name": product_name,
            "quote_mode": "production_mode",
            "validation_status": "passed",
            "structured_input": {"customer_name": "Admin Customer", "product_name": product_name},
            "source_summary": {"source": "quote_admin_test"},
            "customer_name": "Admin Customer",
            "material_total": amount,
            "tiers": [{"quantity": 300, "cost_before_margin": amount, "exw_price": amount + 5}],
            "detail_rows": [
                {
                    "line_no": 1,
                    "name": "fabric",
                    "spec": "600D",
                    "usage": "1m",
                    "unit_price": "10",
                    "amount": amount,
                    "amount_text": f"{amount:.2f}",
                    "source": "uploaded_bom",
                }
            ],
        }

    def _save_quote(self, quote_result, *, sales_user_id="sales-001", quote_uid="admin-series"):
        from mcp_server.tools.quote_save import quote_save

        return quote_save(
            {
                "user_context": self._user_context(role="sales", sales_user_id=sales_user_id),
                "query": {
                    "quote_result": quote_result,
                    "quote_series_uid": quote_uid,
                    "sheet_original_display_name": f"{quote_uid}.xlsx",
                    "structured_input": quote_result["structured_input"],
                    "source_summary": quote_result["source_summary"],
                    "quote_mode": quote_result["quote_mode"],
                    "validation_status": quote_result["validation_status"],
                },
            }
        )

    def _input(self, role="admin", action="approve_quote", query_extra=None, payload=None):
        query = {
            "action": action,
            "quote_uid": "admin-series",
            "payload": payload if payload is not None else {"approval_note": "价格合理"},
        }
        if query_extra:
            query.update(query_extra)
        return {"user_context": self._user_context(role=role), "query": query}

    def test_admin_approve_quote_updates_formal_storage(self):
        from mcp_server.tools.quote_admin import quote_admin

        with self._storage() as storage:
            saved = self._save_quote(self._quote_result("admin-calc-001"))
            result = quote_admin(
                self._input(
                    action="approve_quote",
                    query_extra={"quote_uid": saved["result"]["quote_uid"], "version_no": 1},
                    payload={"approval_note": "可以出正式报价", "reviewer_name": "主管A"},
                )
            )
            detail = storage.load_quote_detail_for_mcp(quote_uid=saved["result"]["quote_uid"])

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["status"], "approved")
        self.assertEqual(detail["approval_status"], "approved")
        self.assertEqual(detail["approval_note"], "可以出正式报价")
        self.assertEqual(detail["admin_feedback"]["approved_by"], "主管A")

    def test_admin_reject_quote_updates_formal_storage_with_note(self):
        from mcp_server.tools.quote_admin import quote_admin

        with self._storage() as storage:
            saved = self._save_quote(self._quote_result("admin-calc-002"))
            result = quote_admin(
                self._input(
                    action="reject_quote",
                    query_extra={"calc_quote_id": saved["result"]["quote_id"]},
                    payload={"approval_note": "辅料价格需复核", "approved_by": "主管B"},
                )
            )
            detail = storage.load_quote_detail_for_mcp(quote_uid=saved["result"]["quote_uid"])

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["status"], "rejected")
        self.assertEqual(detail["approval_status"], "rejected")
        self.assertEqual(detail["approval_note"], "辅料价格需复核")
        self.assertEqual(detail["admin_feedback"]["approved_by"], "主管B")

    def test_view_quote_reads_formal_storage_status(self):
        from mcp_server.tools.quote_admin import quote_admin

        with self._storage() as storage:
            saved = self._save_quote(self._quote_result("admin-calc-003"))
            storage.approve_saved_quote(saved["result"]["quote_uid"], approved_by="后台")
            result = quote_admin(
                self._input(
                    action="view_quote",
                    query_extra={"quote_id": saved["result"]["quote_id"]},
                    payload={},
                )
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["status"], "approved")
        self.assertEqual(result["result"]["quote_id"], "admin-calc-003")
        self.assertIn("quote_summary", result["result"])

    def test_sales_cannot_call_quote_admin_actions(self):
        from mcp_server.tools.quote_admin import quote_admin

        with self._storage():
            self._save_quote(self._quote_result("admin-calc-004"))
            approve = quote_admin(self._input(role="sales", action="approve_quote"))
            reject = quote_admin(self._input(role="sales", action="reject_quote"))

        self.assertFalse(approve["ok"])
        self.assertIn("无权", approve["error"])
        self.assertFalse(reject["ok"])
        self.assertIn("无权", reject["error"])

    def test_system_admin_approve_quote_success(self):
        from mcp_server.tools.quote_admin import quote_admin

        with self._storage() as storage:
            saved = self._save_quote(self._quote_result("admin-calc-005"))
            result = quote_admin(
                self._input(
                    role="system_admin",
                    action="approve_quote",
                    query_extra={"quote_id": saved["result"]["quote_id"]},
                )
            )
            detail = storage.load_quote_detail_for_mcp(quote_uid=saved["result"]["quote_uid"])

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["status"], "approved")
        self.assertEqual(detail["approval_status"], "approved")

    def test_update_price_rule_system_admin_only_and_does_not_touch_price_kb(self):
        from mcp_server.tools.quote_admin import quote_admin

        with patch("mcp_server.tools.quote_admin.QUOTE_ADMIN_PRICE_RULE_PATH", self.rules_path), patch(
            "price_kb.get_price_kb"
        ) as get_price_kb:
            admin = quote_admin(
                self._input(
                    role="admin",
                    action="update_price_rule",
                    query_extra={"quote_uid": "", "quote_id": ""},
                    payload={"rule": "拉链价格需复核"},
                )
            )
            system_admin = quote_admin(
                self._input(
                    role="system_admin",
                    action="update_price_rule",
                    query_extra={"quote_uid": "", "quote_id": ""},
                    payload={"rule": "拉链价格需复核"},
                )
            )

        self.assertFalse(admin["ok"])
        self.assertIn("无权", admin["error"])
        self.assertTrue(system_admin["ok"])
        self.assertEqual(system_admin["result"]["status"], "rule_updated")
        self.assertTrue(self.rules_path.exists())
        get_price_kb.assert_not_called()

    def test_does_not_call_quote_engine_or_legacy_jsonl(self):
        from mcp_server.tools.quote_admin import quote_admin

        with self._storage(), patch("quote_engine.calculate_quote") as engine, patch(
            "quotation_agent.calculator_bridge.run_calculate_quote"
        ) as bridge, patch("mcp_server.tools.quote_admin._read_records") as read_records:
            self._save_quote(self._quote_result("admin-calc-006"))
            result = quote_admin(self._input(action="approve_quote"))

        self.assertTrue(result["ok"])
        engine.assert_not_called()
        bridge.assert_not_called()
        read_records.assert_not_called()

    def test_audit_log_records_action_without_quote_result(self):
        from mcp_server.tools.quote_admin import quote_admin

        with self._storage():
            self._save_quote(self._quote_result("admin-calc-007"))
            quote_admin(
                self._input(
                    action="reject_quote",
                    payload={"approval_note": "规格需确认", "reviewer_name": "主管C"},
                )
            )

        records = [
            json.loads(line)
            for line in self.audit_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        latest = records[-1]
        self.assertEqual(latest["tool"], "quote_admin")
        self.assertEqual(latest["action"], "reject_quote")
        self.assertEqual(latest["quote_uid"], "admin-series")
        self.assertEqual(latest["calc_quote_id"], "admin-calc-007")
        self.assertEqual(latest["status"], "rejected")
        self.assertTrue(latest["success"])
        self.assertNotIn("quote_result", json.dumps(latest, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
