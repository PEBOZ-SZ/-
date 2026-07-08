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


class McpQuoteSheetPreviewTests(unittest.TestCase):
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

    def _quote_result(self, quote_id, *, product_name="Preview Bag", amount=12.5):
        return {
            "quote_id": quote_id,
            "product_name": product_name,
            "quote_mode": "production_mode",
            "validation_status": "passed",
            "structured_input": {
                "customer_name": "Preview Customer",
                "product_name": product_name,
            },
            "source_summary": {"source": "mcp_sheet_preview"},
            "customer_name": "Preview Customer",
            "customer_contact": "Alice",
            "quote_sheet_meta": {
                "cust_name": "Preview Customer",
                "cust_contact": "Alice",
                "sample_required": "pending",
            },
            "material_total": amount,
            "tiers": [
                {
                    "quantity": 300,
                    "cost_before_margin": amount + 3,
                    "exw_price": amount + 8,
                }
            ],
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

    def _save_quote(self, quote_result, *, sales_user_id="sales-001", quote_uid="preview-series"):
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

    def _preview_input(self, role="sales", sales_user_id="sales-001", query=None):
        return {
            "user_context": self._user_context(role=role, sales_user_id=sales_user_id),
            "query": query if query is not None else {"quote_uid": "preview-series"},
        }

    def test_quote_identifier_is_required(self):
        from mcp_server.tools.quote_sheet_preview import quote_sheet_preview

        result = quote_sheet_preview(self._preview_input(query={}))

        self.assertFalse(result["ok"])
        self.assertIn("quote_uid", result["error"])

    def test_sales_user_id_is_not_required_for_quote_sheet_preview(self):
        from mcp_server.tools.quote_sheet_preview import quote_sheet_preview

        with self._storage():
            self._save_quote(self._quote_result("preview-calc-001"))
            result = quote_sheet_preview(self._preview_input(sales_user_id=""))

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["calc_quote_id"], "preview-calc-001")

    def test_sales_can_preview_own_quote_with_url_and_summary(self):
        from mcp_server.tools.quote_sheet_preview import quote_sheet_preview

        with self._storage():
            saved = self._save_quote(self._quote_result("preview-calc-001"))
            result = quote_sheet_preview(
                self._preview_input(
                    query={
                        "quote_uid": saved["result"]["quote_uid"],
                        "mode": "url",
                    }
                )
            )

        self.assertTrue(result["ok"])
        preview = result["result"]
        self.assertEqual(preview["quote_uid"], "preview-series")
        self.assertEqual(preview["calc_quote_id"], "preview-calc-001")
        self.assertEqual(preview["version_id"], saved["result"]["version_id"])
        self.assertEqual(preview["version_no"], 1)
        self.assertEqual(preview["product_name"], "Preview Bag")
        self.assertEqual(preview["approval_status"], "pending")
        self.assertIn("view=quoteSheet", preview["preview_url"])
        self.assertIn("quote_uid=preview-series", preview["preview_url"])
        self.assertTrue(preview["prefill_available"])
        summary = preview["prefill_summary"]
        self.assertEqual(summary["customer_name"], "Preview Customer")
        self.assertEqual(summary["product_name"], "Preview Bag")
        self.assertEqual(summary["rows_count"], 1)
        self.assertIn(summary["suggested_export_lang"], {"cn", "en"})
        self.assertIn("sample_required", summary["needs_user_completion"])
        self.assertNotIn("prefill", preview)

    def test_sales_can_preview_quote_sheet_without_owner_gate(self):
        from mcp_server.tools.quote_sheet_preview import quote_sheet_preview

        with self._storage():
            saved = self._save_quote(
                self._quote_result("preview-private-001"),
                sales_user_id="sales-001",
                quote_uid="private-preview",
            )
            by_uid = quote_sheet_preview(
                self._preview_input(
                    sales_user_id="sales-002",
                    query={"quote_uid": saved["result"]["quote_uid"]},
                )
            )
            by_calc = quote_sheet_preview(
                self._preview_input(
                    sales_user_id="sales-002",
                    query={"calc_quote_id": saved["result"]["quote_id"]},
                )
            )

        for result in (by_uid, by_calc):
            self.assertTrue(result["ok"])
            self.assertEqual(result["result"]["quote_uid"], "private-preview")
            self.assertEqual(result["result"]["calc_quote_id"], "preview-private-001")

    def test_admin_and_system_admin_can_preview_any_quote(self):
        from mcp_server.tools.quote_sheet_preview import quote_sheet_preview

        with self._storage():
            saved = self._save_quote(
                self._quote_result("preview-admin-001"),
                sales_user_id="sales-001",
                quote_uid="admin-preview",
            )
            admin = quote_sheet_preview(
                self._preview_input(
                    role="admin",
                    sales_user_id="",
                    query={"quote_uid": saved["result"]["quote_uid"]},
                )
            )
            system_admin = quote_sheet_preview(
                self._preview_input(
                    role="system_admin",
                    sales_user_id="",
                    query={"calc_quote_id": saved["result"]["quote_id"]},
                )
            )

        self.assertTrue(admin["ok"])
        self.assertTrue(system_admin["ok"])
        self.assertEqual(admin["result"]["quote_uid"], "admin-preview")
        self.assertEqual(system_admin["result"]["calc_quote_id"], "preview-admin-001")

    def test_guest_and_unknown_role_can_preview_quote_sheet(self):
        from mcp_server.tools.quote_sheet_preview import quote_sheet_preview

        for role in ("guest", "owner"):
            with self.subTest(role=role), self._storage():
                self._save_quote(self._quote_result(f"preview-{role}-001"))
                result = quote_sheet_preview(
                    self._preview_input(role=role, query={"quote_uid": "preview-series"})
                )
                self.assertTrue(result["ok"])
                self.assertEqual(result["result"]["quote_uid"], "preview-series")

    def test_latest_version_version_no_and_version_id_targeting(self):
        from mcp_server.tools.quote_sheet_preview import quote_sheet_preview

        with self._storage():
            first = self._save_quote(
                self._quote_result("preview-version-001", product_name="Version One")
            )
            self._save_quote(
                self._quote_result("preview-other-001", product_name="Other"),
                quote_uid="other-preview",
            )
            second = self._save_quote(
                self._quote_result("preview-version-002", product_name="Version Two")
            )
            latest = quote_sheet_preview(self._preview_input(query={"quote_uid": "preview-series"}))
            version_one = quote_sheet_preview(
                self._preview_input(query={"quote_uid": "preview-series", "version_no": 1})
            )
            by_version_id = quote_sheet_preview(
                self._preview_input(
                    query={
                        "quote_uid": "preview-series",
                        "version_id": first["result"]["version_id"],
                    }
                )
            )

        self.assertEqual(second["result"]["version_no"], 2)
        self.assertEqual(latest["result"]["calc_quote_id"], "preview-version-002")
        self.assertEqual(latest["result"]["product_name"], "Version Two")
        self.assertEqual(version_one["result"]["calc_quote_id"], "preview-version-001")
        self.assertEqual(version_one["result"]["product_name"], "Version One")
        self.assertEqual(by_version_id["result"]["calc_quote_id"], "preview-version-001")

    def test_prefill_mode_and_include_prefill_return_sanitized_prefill(self):
        from mcp_server.tools.quote_sheet_preview import quote_sheet_preview

        with self._storage():
            self._save_quote(self._quote_result("preview-prefill-001"))
            prefill_mode = quote_sheet_preview(
                self._preview_input(query={"quote_uid": "preview-series", "mode": "prefill"})
            )
            include_prefill = quote_sheet_preview(
                self._preview_input(
                    query={
                        "quote_uid": "preview-series",
                        "mode": "url",
                        "include_prefill": True,
                    }
                )
            )

        for result in (prefill_mode, include_prefill):
            self.assertTrue(result["ok"])
            prefill = result["result"]["prefill"]
            self.assertEqual(prefill["quote_series_uid"], "preview-series")
            self.assertEqual(prefill["source"], "record")
            self.assertIn("meta", prefill)
            self.assertIn("rows", prefill)
            self.assertLessEqual(len(prefill["rows"]), 10)
            self.assertNotIn("quote_result", json.dumps(prefill, ensure_ascii=False))
            self.assertNotIn("detail_rows", json.dumps(prefill, ensure_ascii=False))
            self.assertNotIn("quote_json", json.dumps(prefill, ensure_ascii=False))

    def test_does_not_recalculate_read_legacy_jsonl_or_generate_pdf(self):
        from mcp_server.tools.quote_sheet_preview import quote_sheet_preview

        with self._storage(), patch("quote_engine.calculate_quote") as quote_engine, patch(
            "quotation_agent.calculator_bridge.run_calculate_quote"
        ) as bridge, patch("pathlib.Path.read_text") as read_text, patch(
            "mcp_server.tools.quote_sheet_preview.html2pdf", create=True
        ) as html2pdf:
            self._save_quote(self._quote_result("preview-safe-001"))
            result = quote_sheet_preview(self._preview_input(query={"quote_uid": "preview-series"}))

        self.assertTrue(result["ok"])
        quote_engine.assert_not_called()
        bridge.assert_not_called()
        read_text.assert_not_called()
        html2pdf.assert_not_called()

    def test_audit_log_records_summary_only(self):
        from mcp_server.tools.quote_sheet_preview import quote_sheet_preview

        with self._storage():
            self._save_quote(self._quote_result("preview-audit-001"))
            result = quote_sheet_preview(
                self._preview_input(
                    query={
                        "quote_uid": "preview-series",
                        "mode": "prefill",
                        "include_prefill": True,
                    }
                )
            )

        self.assertTrue(result["ok"])
        records = [
            json.loads(line)
            for line in self.audit_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        latest = records[-1]
        serialized = json.dumps(latest, ensure_ascii=False)
        self.assertEqual(latest["tool"], "quote_sheet_preview")
        self.assertEqual(latest["quote_uid"], "preview-series")
        self.assertEqual(latest["mode"], "prefill")
        self.assertNotIn("quote_result", serialized)
        self.assertNotIn("detail_rows", serialized)
        self.assertNotIn("quote_json", serialized)


if __name__ == "__main__":
    unittest.main()
