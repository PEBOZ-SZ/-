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


class McpQuoteApprovalStatusTests(unittest.TestCase):
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

    def _user_context(self, role="sales", sales_user_id="sales-001"):
        return {
            "user_id": sales_user_id or f"{role}-user",
            "user_name": f"{role}-user",
            "role": role,
            "session_id": f"sess-{role}-{sales_user_id or 'none'}",
            "sales_user_id": sales_user_id,
            "sales_user_name": f"name-{sales_user_id}" if sales_user_id else "",
            "sales_user_code": "S001" if sales_user_id else "",
        }

    def _quote_result(self, calc_id, *, product_name="Approval Bag", amount=10):
        return {
            "quote_id": calc_id,
            "product_name": product_name,
            "quote_mode": "production_mode",
            "validation_status": "passed",
            "structured_input": {"customer_name": "Approval Customer"},
            "source_summary": {"source": "approval_status_test"},
            "customer_name": "Approval Customer",
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

    def _save_quote(self, quote_result, *, sales_user_id="sales-001", quote_uid="approval-series"):
        from mcp_server.tools.quote_save import quote_save

        return quote_save(
            {
                "user_context": self._user_context(sales_user_id=sales_user_id),
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

    def _input(self, role="sales", sales_user_id="sales-001", query=None):
        return {
            "user_context": self._user_context(role=role, sales_user_id=sales_user_id),
            "query": query if query is not None else {"quote_uid": "approval-series"},
        }

    def test_quote_identifier_is_required(self):
        from mcp_server.tools.quote_approval_status import quote_approval_status

        result = quote_approval_status(self._input(query={}))

        self.assertFalse(result["ok"])
        self.assertIn("quote_uid", result["error"])

    def test_sales_user_id_is_required_for_sales(self):
        from mcp_server.tools.quote_approval_status import quote_approval_status

        with self._storage():
            self._save_quote(self._quote_result("approval-calc-001"))
            result = quote_approval_status(self._input(sales_user_id=""))

        self.assertFalse(result["ok"])
        self.assertIn("sales_user_id", result["error"])

    def test_sales_can_query_own_pending_status(self):
        from mcp_server.tools.quote_approval_status import quote_approval_status

        with self._storage():
            saved = self._save_quote(self._quote_result("approval-calc-001"))
            result = quote_approval_status(self._input(query={"quote_uid": saved["result"]["quote_uid"]}))

        self.assertTrue(result["ok"])
        status = result["result"]
        self.assertEqual(status["quote_uid"], "approval-series")
        self.assertEqual(status["calc_quote_id"], "approval-calc-001")
        self.assertEqual(status["version_id"], saved["result"]["version_id"])
        self.assertEqual(status["version_no"], 1)
        self.assertEqual(status["approval_status"], "pending")
        self.assertEqual(status["approval_note"], "")
        self.assertFalse(status["export_readiness"]["can_export"])
        self.assertIn("pending", status["export_readiness"]["reason"])
        self.assertEqual(status["admin_feedback"]["feedback_type"], "none")

    def test_sales_cannot_query_other_sales_quote(self):
        from mcp_server.tools.quote_approval_status import quote_approval_status

        with self._storage():
            saved = self._save_quote(
                self._quote_result("approval-private-001"),
                sales_user_id="sales-001",
                quote_uid="private-approval",
            )
            by_uid = quote_approval_status(
                self._input(sales_user_id="sales-002", query={"quote_uid": saved["result"]["quote_uid"]})
            )
            by_calc = quote_approval_status(
                self._input(sales_user_id="sales-002", query={"calc_quote_id": saved["result"]["quote_id"]})
            )

        for result in (by_uid, by_calc):
            self.assertFalse(result["ok"])
            self.assertIn("不存在或无权", result["error"])
            self.assertNotIn("private-approval", result["error"])
            self.assertNotIn("approval-private-001", result["error"])

    def test_admin_and_system_admin_can_query_any_quote(self):
        from mcp_server.tools.quote_approval_status import quote_approval_status

        with self._storage():
            saved = self._save_quote(
                self._quote_result("approval-admin-001"),
                sales_user_id="sales-001",
                quote_uid="admin-approval",
            )
            admin = quote_approval_status(
                self._input(role="admin", sales_user_id="", query={"quote_uid": saved["result"]["quote_uid"]})
            )
            system_admin = quote_approval_status(
                self._input(role="system_admin", sales_user_id="", query={"calc_quote_id": saved["result"]["quote_id"]})
            )

        self.assertTrue(admin["ok"])
        self.assertTrue(system_admin["ok"])
        self.assertEqual(admin["result"]["quote_uid"], "admin-approval")
        self.assertEqual(system_admin["result"]["calc_quote_id"], "approval-admin-001")

    def test_guest_and_unknown_role_are_denied(self):
        from mcp_server.tools.quote_approval_status import quote_approval_status

        for role in ("guest", "owner"):
            with self.subTest(role=role), self._storage():
                self._save_quote(self._quote_result(f"approval-{role}-001"))
                result = quote_approval_status(self._input(role=role, query={"quote_uid": "approval-series"}))
                self.assertFalse(result["ok"])
                self.assertIn("quote_approval_status", result["error"])

    def test_latest_version_version_no_and_version_id_targeting(self):
        from mcp_server.tools.quote_approval_status import quote_approval_status

        with self._storage():
            first = self._save_quote(self._quote_result("approval-version-001", product_name="Version One"))
            second = self._save_quote(self._quote_result("approval-version-002", product_name="Version Two"))
            latest = quote_approval_status(self._input(query={"quote_uid": "approval-series"}))
            version_one = quote_approval_status(
                self._input(query={"quote_uid": "approval-series", "version_no": 1})
            )
            by_version_id = quote_approval_status(
                self._input(query={"quote_uid": "approval-series", "version_id": first["result"]["version_id"]})
            )

        self.assertEqual(second["result"]["version_no"], 2)
        self.assertEqual(latest["result"]["calc_quote_id"], "approval-version-002")
        self.assertEqual(version_one["result"]["calc_quote_id"], "approval-version-001")
        self.assertEqual(by_version_id["result"]["calc_quote_id"], "approval-version-001")

    def test_approved_status_can_export(self):
        from mcp_server.tools.quote_approval_status import quote_approval_status

        with self._storage() as storage:
            self._save_quote(self._quote_result("approval-approved-001"))
            storage.update_saved_quote_approval(
                "approval-series",
                approval_status="approved",
                approval_note="OK",
                reviewed_by="admin-user",
            )
            result = quote_approval_status(self._input(query={"quote_uid": "approval-series"}))

        self.assertTrue(result["ok"])
        status = result["result"]
        self.assertEqual(status["approval_status"], "approved")
        self.assertEqual(status["approval_note"], "OK")
        self.assertEqual(status["approved_by"], "admin-user")
        self.assertTrue(status["approval_updated_at"])
        self.assertTrue(status["export_readiness"]["can_export"])
        self.assertEqual(status["admin_feedback"]["feedback_type"], "approved")

    def test_reads_status_after_mcp_admin_approval(self):
        from mcp_server.tools.quote_admin import quote_admin
        from mcp_server.tools.quote_approval_status import quote_approval_status

        with self._storage():
            saved = self._save_quote(self._quote_result("approval-admin-001"))
            approved = quote_admin(
                {
                    "user_context": self._user_context(role="admin", sales_user_id=""),
                    "query": {
                        "action": "approve_quote",
                        "quote_uid": saved["result"]["quote_uid"],
                        "payload": {"approval_note": "MCP approved", "reviewer_name": "MCP reviewer"},
                    },
                }
            )
            status = quote_approval_status(
                self._input(query={"quote_uid": saved["result"]["quote_uid"]})
            )

        self.assertTrue(approved["ok"])
        self.assertTrue(status["ok"])
        self.assertEqual(status["result"]["approval_status"], "approved")
        self.assertEqual(status["result"]["approval_note"], "MCP approved")
        self.assertEqual(status["result"]["approved_by"], "MCP reviewer")
        self.assertTrue(status["result"]["export_readiness"]["can_export"])

    def test_rejected_status_returns_note_and_feedback_summary(self):
        from mcp_server.tools.quote_approval_status import quote_approval_status

        with self._storage() as storage:
            self._save_quote(self._quote_result("approval-rejected-001"))
            storage.update_saved_quote_approval(
                "approval-series",
                approval_status="rejected",
                approval_note="价格需要调整",
                reviewed_by="admin-user",
            )
            result = quote_approval_status(self._input(query={"quote_uid": "approval-series"}))

        self.assertTrue(result["ok"])
        status = result["result"]
        self.assertEqual(status["approval_status"], "rejected")
        self.assertEqual(status["approval_note"], "价格需要调整")
        self.assertFalse(status["export_readiness"]["can_export"])
        self.assertEqual(status["admin_feedback"]["feedback_type"], "rejected")
        self.assertIn("价格需要调整", status["admin_feedback"]["summary"])
        self.assertNotIn("quote_result", json.dumps(status["admin_feedback"], ensure_ascii=False))

    def test_frozen_and_exported_statuses_are_reflected_without_reinterpreting_fields(self):
        from mcp_server.tools.quote_approval_status import quote_approval_status

        with self._storage() as storage:
            self._save_quote(self._quote_result("approval-frozen-001"), quote_uid="frozen-series")
            self._save_quote(self._quote_result("approval-exported-001"), quote_uid="exported-series")
            storage.init_quote_storage()
            conn = storage._connect()
            try:
                conn.execute("UPDATE quotes SET approval_status = ? WHERE quote_uid = ?", ("frozen", "frozen-series"))
                conn.execute("UPDATE quotes SET approval_status = ? WHERE quote_uid = ?", ("exported", "exported-series"))
                conn.commit()
            finally:
                conn.close()
            frozen = quote_approval_status(self._input(query={"quote_uid": "frozen-series"}))
            exported = quote_approval_status(self._input(query={"quote_uid": "exported-series"}))

        self.assertEqual(frozen["result"]["approval_status"], "frozen")
        self.assertFalse(frozen["result"]["export_readiness"]["can_export"])
        self.assertEqual(exported["result"]["approval_status"], "exported")
        self.assertTrue(exported["result"]["export_readiness"]["can_export"])

    def test_admin_corrected_quote_returns_summary_only(self):
        from mcp_server.tools.quote_approval_status import quote_approval_status

        with self._storage():
            self._save_quote(self._quote_result("approval-corrected-001", product_name="Original"))
            self._save_quote(self._quote_result("approval-corrected-002", product_name="Corrected"))
            result = quote_approval_status(
                self._input(query={"quote_uid": "approval-series", "include_admin_feedback": True})
            )

        feedback = result["result"]["admin_feedback"]
        serialized = json.dumps(feedback, ensure_ascii=False)
        self.assertTrue(feedback["has_admin_corrected_quote"])
        self.assertIn("Corrected", feedback["summary"])
        self.assertNotIn("detail_rows", serialized)
        self.assertNotIn("quote_json", serialized)
        self.assertNotIn("admin_corrected_quote_result", serialized)

    def test_include_flags_can_omit_feedback_and_readiness(self):
        from mcp_server.tools.quote_approval_status import quote_approval_status

        with self._storage():
            self._save_quote(self._quote_result("approval-flags-001"))
            result = quote_approval_status(
                self._input(
                    query={
                        "quote_uid": "approval-series",
                        "include_admin_feedback": False,
                        "include_export_readiness": False,
                    }
                )
            )

        self.assertTrue(result["ok"])
        self.assertNotIn("admin_feedback", result["result"])
        self.assertNotIn("export_readiness", result["result"])

    def test_does_not_recalculate_read_legacy_jsonl_or_generate_pdf(self):
        from mcp_server.tools.quote_approval_status import quote_approval_status

        with self._storage(), patch("quote_engine.calculate_quote") as quote_engine, patch(
            "quotation_agent.calculator_bridge.run_calculate_quote"
        ) as bridge, patch("pathlib.Path.read_text") as read_text, patch(
            "mcp_server.tools.quote_export_pdf._generate_pdf"
        ) as generate_pdf:
            self._save_quote(self._quote_result("approval-safe-001"))
            result = quote_approval_status(self._input(query={"quote_uid": "approval-series"}))

        self.assertTrue(result["ok"])
        quote_engine.assert_not_called()
        bridge.assert_not_called()
        read_text.assert_not_called()
        generate_pdf.assert_not_called()

    def test_audit_log_records_summary_only(self):
        from mcp_server.tools.quote_approval_status import quote_approval_status

        with self._storage() as storage:
            self._save_quote(self._quote_result("approval-audit-001"))
            storage.update_saved_quote_approval(
                "approval-series",
                approval_status="rejected",
                approval_note="audit note",
                reviewed_by="admin-user",
            )
            result = quote_approval_status(self._input(query={"quote_uid": "approval-series"}))

        self.assertTrue(result["ok"])
        records = [
            json.loads(line)
            for line in self.audit_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        latest = records[-1]
        serialized = json.dumps(latest, ensure_ascii=False)
        self.assertEqual(latest["tool"], "quote_approval_status")
        self.assertEqual(latest["quote_uid"], "approval-series")
        self.assertEqual(latest["approval_status"], "rejected")
        self.assertNotIn("quote_result", serialized)
        self.assertNotIn("detail_rows", serialized)
        self.assertNotIn("quote_json", serialized)
        self.assertNotIn("admin_corrected_quote", serialized)


if __name__ == "__main__":
    unittest.main()
