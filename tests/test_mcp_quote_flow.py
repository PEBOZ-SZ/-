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


class McpQuoteFlowTests(unittest.TestCase):
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
        }

    def _payload(self, product_name="Flow Bag"):
        return {
            "product_name": product_name,
            "quantities": [300],
            "items": [{"name": "fabric", "spec": "600D", "amount": 12.5}],
        }

    def _quote_result(self, quote_id, *, product_name="Flow Bag", amount=12.5):
        return {
            "quote_id": quote_id,
            "product_name": product_name,
            "quote_mode": "production_mode",
            "validation_status": "passed",
            "structured_input": {"customer_name": "Flow Customer", "product_name": product_name},
            "source_summary": {"source": "mcp_flow"},
            "material_total": amount,
            "tiers": [{"quantity": 300, "cost_before_margin": amount + 3, "exw_price": amount + 8}],
            "detail_rows": [
                {
                    "line_no": 1,
                    "name": "fabric",
                    "spec": "600D",
                    "usage": "1m",
                    "unit_price": "12.5",
                    "amount": amount,
                    "amount_text": f"{amount:.2f}",
                    "source": "uploaded_bom",
                }
            ],
            "total_price": amount + 8,
        }

    def _save_input(self, quote_result, role="sales", sales_user_id="sales-001", quote_uid="flow-series"):
        return {
            "user_context": self._user_context(role=role, sales_user_id=sales_user_id),
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

    def _save_quote(self, quote_result, role="sales", sales_user_id="sales-001", quote_uid="flow-series"):
        from mcp_server.tools.quote_save import quote_save

        return quote_save(
            self._save_input(
                quote_result,
                role=role,
                sales_user_id=sales_user_id,
                quote_uid=quote_uid,
            )
        )

    def test_sales_calculate_save_history_detail_closed_loop(self):
        from mcp_server.tools.quote_calculate import quote_calculate
        from mcp_server.tools.quote_get_detail import quote_get_detail
        from mcp_server.tools.quote_get_history import quote_get_history

        quote_result = self._quote_result("flow-calc-001")
        with self._storage(), patch(
            "quotation_agent.calculator_bridge.run_calculate_quote",
            return_value=quote_result,
        ) as calculate_bridge, patch("quote_engine.calculate_quote") as quote_engine:
            import quote_upload_storage as storage

            calculated = quote_calculate(
                {"user_context": self._user_context(), "payload": self._payload()}
            )
            save_ready_quote = dict(calculated["result"])
            save_ready_quote.update(
                {
                    "quote_id": quote_result["quote_id"],
                    "quote_mode": quote_result["quote_mode"],
                    "validation_status": quote_result["validation_status"],
                    "structured_input": quote_result["structured_input"],
                    "source_summary": quote_result["source_summary"],
                    "detail_rows": quote_result["detail_rows"],
                    "total_price": quote_result["total_price"],
                }
            )
            save_result = self._save_quote(save_ready_quote)
            history = quote_get_history(
                {"user_context": self._user_context(), "query": {"limit": 10, "offset": 0}}
            )
            item = history["result"]["items"][0]
            detail = quote_get_detail(
                {
                    "user_context": self._user_context(),
                    "query": {
                        "quote_uid": item["quote_uid"],
                        "calc_quote_id": item["latest_calc_quote_id"],
                    },
                }
            )
            stored_version = storage.resolve_quote_version_target(
                "flow-series",
                calc_quote_id="flow-calc-001",
            )

        self.assertTrue(calculated["ok"])
        self.assertTrue(save_result["ok"])
        self.assertTrue(history["ok"])
        self.assertTrue(detail["ok"])
        self.assertEqual(item["quote_uid"], "flow-series")
        self.assertEqual(item["latest_calc_quote_id"], "flow-calc-001")
        self.assertEqual(item["latest_version_no"], 1)
        self.assertEqual(detail["result"]["quote_result"]["product_name"], "Flow Bag")
        self.assertEqual(detail["result"]["detail_rows"][0]["name"], "fabric")
        self.assertEqual(save_result["result"]["version_id"], stored_version["id"])
        self.assertEqual(detail["result"]["version_id"], save_result["result"]["version_id"])
        self.assertEqual(detail["result"]["version_no"], 1)
        self.assertEqual(detail["result"]["approval_status"], "pending")
        self.assertEqual(detail["result"]["approval_note"], "")
        self.assertEqual(detail["result"]["structured_input"]["customer_name"], "Flow Customer")
        self.assertEqual(detail["result"]["source_summary"], {"source": "mcp_flow"})
        self.assertEqual(detail["result"]["validation_status"], "passed")
        self.assertEqual(detail["result"]["quote_mode"], "production_mode")
        calculate_bridge.assert_called_once()
        quote_engine.assert_not_called()

    def test_sales_permission_isolation_for_history_and_detail(self):
        from mcp_server.tools.quote_get_detail import quote_get_detail
        from mcp_server.tools.quote_get_history import quote_get_history

        with self._storage():
            saved = self._save_quote(
                self._quote_result("flow-private-001"),
                sales_user_id="sales-001",
                quote_uid="private-series",
            )
            history = quote_get_history(
                {
                    "user_context": self._user_context(sales_user_id="sales-002"),
                    "query": {"limit": 10, "offset": 0},
                }
            )
            by_uid = quote_get_detail(
                {
                    "user_context": self._user_context(sales_user_id="sales-002"),
                    "query": {"quote_uid": saved["result"]["quote_uid"]},
                }
            )
            by_calc = quote_get_detail(
                {
                    "user_context": self._user_context(sales_user_id="sales-002"),
                    "query": {"calc_quote_id": saved["result"]["quote_id"]},
                }
            )

        self.assertTrue(saved["ok"])
        self.assertTrue(history["ok"])
        self.assertEqual(history["result"]["items"], [])
        for result in (by_uid, by_calc):
            self.assertFalse(result["ok"])
            self.assertIn("不存在或无权", result["error"])
            self.assertNotIn("private-series", result["error"])
            self.assertNotIn("flow-private-001", result["error"])

    def test_admin_and_system_admin_can_read_all_history_and_detail(self):
        from mcp_server.tools.quote_get_detail import quote_get_detail
        from mcp_server.tools.quote_get_history import quote_get_history

        with self._storage():
            saved = self._save_quote(
                self._quote_result("flow-admin-001"),
                sales_user_id="sales-001",
                quote_uid="admin-visible-series",
            )
            admin_history = quote_get_history(
                {"user_context": self._user_context(role="admin", sales_user_id=""), "query": {}}
            )
            system_history = quote_get_history(
                {
                    "user_context": self._user_context(role="system_admin", sales_user_id=""),
                    "query": {},
                }
            )
            admin_detail = quote_get_detail(
                {
                    "user_context": self._user_context(role="admin", sales_user_id=""),
                    "query": {"quote_uid": saved["result"]["quote_uid"]},
                }
            )
            system_detail = quote_get_detail(
                {
                    "user_context": self._user_context(role="system_admin", sales_user_id=""),
                    "query": {"calc_quote_id": saved["result"]["quote_id"]},
                }
            )

        self.assertTrue(admin_history["ok"])
        self.assertTrue(system_history["ok"])
        self.assertEqual(admin_history["result"]["count"], 1)
        self.assertEqual(system_history["result"]["count"], 1)
        self.assertTrue(admin_detail["ok"])
        self.assertTrue(system_detail["ok"])
        self.assertEqual(admin_detail["result"]["quote_uid"], "admin-visible-series")
        self.assertEqual(system_detail["result"]["calc_quote_id"], "flow-admin-001")

    def test_guest_and_unknown_roles_are_denied_for_core_stateful_tools(self):
        from mcp_server.tools.quote_get_detail import quote_get_detail
        from mcp_server.tools.quote_get_history import quote_get_history
        from mcp_server.tools.quote_save import quote_save

        for role in ("guest", "owner"):
            with self.subTest(role=role), self._storage():
                save_result = quote_save(
                    self._save_input(self._quote_result(f"flow-{role}-001"), role=role)
                )
                history = quote_get_history(
                    {"user_context": self._user_context(role=role), "query": {}}
                )
                detail = quote_get_detail(
                    {
                        "user_context": self._user_context(role=role),
                        "query": {"quote_uid": "any-series"},
                    }
                )

            self.assertFalse(save_result["ok"])
            self.assertFalse(history["ok"])
            self.assertFalse(detail["ok"])

    def test_saved_versions_can_be_located_by_latest_version_no_version_no_and_version_id(self):
        from mcp_server.tools.quote_get_detail import quote_get_detail
        from mcp_server.tools.quote_get_history import quote_get_history

        with self._storage():
            first = self._save_quote(self._quote_result("flow-version-001", product_name="Version One"))
            self._save_quote(
                self._quote_result("flow-other-series-001", product_name="Other Series"),
                quote_uid="other-series",
            )
            second = self._save_quote(
                self._quote_result("flow-version-002", product_name="Version Two")
            )
            history = quote_get_history(
                {"user_context": self._user_context(), "query": {"limit": 10, "offset": 0}}
            )
            latest = quote_get_detail(
                {
                    "user_context": self._user_context(),
                    "query": {"quote_uid": "flow-series"},
                }
            )
            version_one = quote_get_detail(
                {
                    "user_context": self._user_context(),
                    "query": {"quote_uid": "flow-series", "version_no": 1},
                }
            )
            by_version_id = quote_get_detail(
                {
                    "user_context": self._user_context(),
                    "query": {"quote_uid": "flow-series", "version_id": first["result"]["version_id"]},
                }
            )
            by_second_version_id = quote_get_detail(
                {
                    "user_context": self._user_context(),
                    "query": {"quote_uid": "flow-series", "version_id": second["result"]["version_id"]},
                }
            )

        self.assertTrue(second["ok"])
        self.assertNotEqual(second["result"]["version_id"], second["result"]["version_no"])
        self.assertEqual(history["result"]["items"][0]["latest_version_no"], 2)
        self.assertEqual(latest["result"]["calc_quote_id"], "flow-version-002")
        self.assertEqual(latest["result"]["quote_result"]["product_name"], "Version Two")
        self.assertEqual(version_one["result"]["calc_quote_id"], "flow-version-001")
        self.assertEqual(version_one["result"]["quote_result"]["product_name"], "Version One")
        self.assertEqual(by_version_id["result"]["calc_quote_id"], "flow-version-001")
        self.assertEqual(by_second_version_id["result"]["calc_quote_id"], "flow-version-002")

    def test_approval_status_flows_through_history_and_detail(self):
        from mcp_server.tools.quote_get_detail import quote_get_detail
        from mcp_server.tools.quote_get_history import quote_get_history

        with self._storage() as storage:
            self._save_quote(self._quote_result("flow-approval-001"), quote_uid="approval-series")
            storage.update_saved_quote_approval(
                "approval-series",
                approval_status="approved",
                approval_note="approved by flow test",
                reviewed_by="admin",
            )
            history = quote_get_history(
                {
                    "user_context": self._user_context(role="admin", sales_user_id=""),
                    "query": {"approval_status": "approved"},
                }
            )
            detail = quote_get_detail(
                {
                    "user_context": self._user_context(role="admin", sales_user_id=""),
                    "query": {"quote_uid": "approval-series"},
                }
            )

        self.assertEqual(history["result"]["items"][0]["approval_status"], "approved")
        self.assertEqual(detail["result"]["approval_status"], "approved")
        self.assertEqual(detail["result"]["approval_note"], "approved by flow test")

    def test_core_flow_does_not_read_legacy_mcp_jsonl_or_recalculate_saved_detail(self):
        from mcp_server.tools.quote_get_detail import quote_get_detail
        from mcp_server.tools.quote_get_history import quote_get_history

        with self._storage(), patch("pathlib.Path.read_text") as read_text, patch(
            "quote_engine.calculate_quote"
        ) as quote_engine, patch("quotation_agent.calculator_bridge.run_calculate_quote") as bridge:
            saved = self._save_quote(self._quote_result("flow-no-jsonl-001"))
            history = quote_get_history({"user_context": self._user_context(), "query": {}})
            detail = quote_get_detail(
                {
                    "user_context": self._user_context(),
                    "query": {"quote_uid": saved["result"]["quote_uid"]},
                }
            )

        self.assertTrue(saved["ok"])
        self.assertTrue(history["ok"])
        self.assertTrue(detail["ok"])
        read_text.assert_not_called()
        quote_engine.assert_not_called()
        bridge.assert_not_called()

    def test_audit_log_contains_summary_without_large_payloads(self):
        from mcp_server.tools.quote_get_detail import quote_get_detail
        from mcp_server.tools.quote_get_history import quote_get_history

        with self._storage():
            saved = self._save_quote(self._quote_result("flow-audit-001"))
            quote_get_history({"user_context": self._user_context(), "query": {}})
            quote_get_detail(
                {
                    "user_context": self._user_context(),
                    "query": {"quote_uid": saved["result"]["quote_uid"]},
                }
            )

        records = [
            json.loads(line)
            for line in self.audit_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        tools = {record.get("tool") for record in records}
        serialized = "\n".join(json.dumps(record, ensure_ascii=False) for record in records)
        self.assertIn("quote_save", tools)
        self.assertIn("quote_get_history", tools)
        self.assertIn("quote_get_detail", tools)
        self.assertNotIn("quote_result", serialized)
        self.assertNotIn("detail_rows", serialized)
        self.assertNotIn("quote_json", serialized)


if __name__ == "__main__":
    unittest.main()
