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


class McpQuoteExportPdfTests(unittest.TestCase):
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
        from mcp_server.tools import quote_export_pdf as export_pdf_mod

        old_db_path = storage.DB_PATH
        old_data_dir = storage.DATA_DIR
        old_uploads_dir = storage.UPLOADS_DIR
        old_export_dir = export_pdf_mod.QUOTE_EXPORT_PDF_DIR
        root = Path(self.tmpdir.name)
        storage.DATA_DIR = root
        storage.UPLOADS_DIR = root / "uploads"
        storage.DB_PATH = root / "quotes.db"
        export_pdf_mod.QUOTE_EXPORT_PDF_DIR = root / "exports"
        try:
            yield storage
        finally:
            storage.DB_PATH = old_db_path
            storage.DATA_DIR = old_data_dir
            storage.UPLOADS_DIR = old_uploads_dir
            export_pdf_mod.QUOTE_EXPORT_PDF_DIR = old_export_dir

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

    def _quote_result(self, quote_id, *, product_name="Export Bag", amount=12.5, include_fob=False):
        return {
            "quote_id": quote_id,
            "product_name": product_name,
            "quote_mode": "production_mode",
            "validation_status": "passed",
            "structured_input": {
                "customer_name": "Export Customer",
                "product_name": product_name,
            },
            "source_summary": {"source": "mcp_export_pdf"},
            "customer_name": "Export Customer",
            "customer_contact": "Alice",
            "include_fob": include_fob,
            "quote_sheet_meta": {
                "cust_name": "Export Customer",
                "cust_contact": "Alice",
                "sample_required": "yes",
                "sample_fee": "100",
                "sample_lead_time": "7 days",
                "payee_company_name": "PEBOZ",
            },
            "material_total": amount,
            "tiers": [
                {
                    "quantity": 300,
                    "cost_before_margin": amount + 3,
                    "exw_price": amount + 8,
                    "fob_price": amount + 12,
                    "fob_price_usd": 3.5,
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

    def _save_quote(self, quote_result, *, sales_user_id="sales-001", quote_uid="export-series"):
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

    def _approve_quote(self, storage, quote_uid="export-series", *, approved_by="admin"):
        return storage.approve_saved_quote(quote_uid, approved_by=approved_by)

    def _export_input(self, role="sales", sales_user_id="sales-001", query=None):
        return {
            "user_context": self._user_context(role=role, sales_user_id=sales_user_id),
            "query": query if query is not None else {"quote_uid": "export-series"},
        }

    def test_quote_identifier_is_required(self):
        from mcp_server.tools.quote_export_pdf import quote_export_pdf

        result = quote_export_pdf(self._export_input(query={}))

        self.assertFalse(result["ok"])
        self.assertIn("quote_uid", result["error"])

    def test_sales_user_id_is_required_for_sales(self):
        from mcp_server.tools.quote_export_pdf import quote_export_pdf

        with self._storage():
            self._save_quote(self._quote_result("export-calc-001"))
            result = quote_export_pdf(self._export_input(sales_user_id=""))

        self.assertFalse(result["ok"])
        self.assertIn("sales_user_id", result["error"])

    def test_pending_quote_cannot_export_pdf(self):
        from mcp_server.tools.quote_export_pdf import quote_export_pdf

        with self._storage():
            saved = self._save_quote(self._quote_result("export-calc-001"))
            result = quote_export_pdf(
                self._export_input(
                    query={
                        "quote_uid": saved["result"]["quote_uid"],
                        "lang": "cn",
                        "currency_mode": "rmb",
                    }
                )
            )

        self.assertFalse(result["ok"])
        self.assertIn("待管理员审批", result["error"])

    def test_rejected_quote_cannot_export_pdf_and_returns_rejection_hint(self):
        from mcp_server.tools.quote_export_pdf import quote_export_pdf

        with self._storage() as storage:
            saved = self._save_quote(self._quote_result("export-rejected-001"))
            storage.update_saved_quote_approval(
                saved["result"]["quote_uid"],
                approval_status="rejected",
                approval_note="辅料价格需复核",
                reviewed_by="admin",
            )
            result = quote_export_pdf(
                self._export_input(
                    query={
                        "quote_uid": saved["result"]["quote_uid"],
                        "lang": "cn",
                        "currency_mode": "rmb",
                    }
                )
            )

        self.assertFalse(result["ok"])
        self.assertIn("已被驳回", result["error"])
        self.assertIn("辅料价格需复核", result["error"])

    def test_sales_can_export_approved_own_quote_pdf(self):
        from mcp_server.tools.quote_export_pdf import quote_export_pdf

        with self._storage() as storage:
            saved = self._save_quote(self._quote_result("export-calc-001"))
            self._approve_quote(storage, saved["result"]["quote_uid"])
            result = quote_export_pdf(
                self._export_input(
                    query={
                        "quote_uid": saved["result"]["quote_uid"],
                        "lang": "cn",
                        "currency_mode": "rmb",
                    }
                )
            )

        self.assertTrue(result["ok"])
        export = result["result"]
        self.assertEqual(export["quote_uid"], "export-series")
        self.assertEqual(export["calc_quote_id"], "export-calc-001")
        self.assertEqual(export["version_id"], saved["result"]["version_id"])
        self.assertEqual(export["version_no"], 1)
        self.assertEqual(export["export_lang"], "cn")
        self.assertEqual(export["currency_mode"], "rmb")
        self.assertEqual(export["export_status"], "generated")
        self.assertTrue(export["file_name"].endswith(".pdf"))
        path = Path(export["file_path"])
        self.assertTrue(path.exists())
        self.assertGreater(export["file_size"], 100)
        self.assertEqual(path.read_bytes()[:4], b"%PDF")
        self.assertIn("download_url", export)
        self.assertEqual(export["prefill_summary"]["product_name"], "Export Bag")

    def test_sales_cannot_export_other_sales_quote(self):
        from mcp_server.tools.quote_export_pdf import quote_export_pdf

        with self._storage() as storage:
            saved = self._save_quote(
                self._quote_result("export-private-001"),
                sales_user_id="sales-001",
                quote_uid="private-export",
            )
            self._approve_quote(storage, saved["result"]["quote_uid"])
            by_uid = quote_export_pdf(
                self._export_input(
                    sales_user_id="sales-002",
                    query={"quote_uid": saved["result"]["quote_uid"]},
                )
            )
            by_calc = quote_export_pdf(
                self._export_input(
                    sales_user_id="sales-002",
                    query={"calc_quote_id": saved["result"]["quote_id"]},
                )
            )

        for result in (by_uid, by_calc):
            self.assertFalse(result["ok"])
            self.assertIn("不存在或无权", result["error"])
            self.assertNotIn("private-export", result["error"])
            self.assertNotIn("export-private-001", result["error"])

    def test_admin_and_system_admin_can_export_any_quote(self):
        from mcp_server.tools.quote_export_pdf import quote_export_pdf

        with self._storage() as storage:
            saved = self._save_quote(
                self._quote_result("export-admin-001"),
                sales_user_id="sales-001",
                quote_uid="admin-export",
            )
            self._approve_quote(storage, saved["result"]["quote_uid"])
            admin = quote_export_pdf(
                self._export_input(
                    role="admin",
                    sales_user_id="",
                    query={"quote_uid": saved["result"]["quote_uid"], "dry_run": True},
                )
            )
            system_admin = quote_export_pdf(
                self._export_input(
                    role="system_admin",
                    sales_user_id="",
                    query={"calc_quote_id": saved["result"]["quote_id"], "dry_run": True},
                )
            )

        self.assertTrue(admin["ok"])
        self.assertTrue(system_admin["ok"])
        self.assertTrue(admin["result"]["can_export"])
        self.assertTrue(system_admin["result"]["can_export"])

    def test_guest_and_unknown_role_are_denied(self):
        from mcp_server.tools.quote_export_pdf import quote_export_pdf

        for role in ("guest", "owner"):
            with self.subTest(role=role), self._storage():
                self._save_quote(self._quote_result(f"export-{role}-001"))
                result = quote_export_pdf(
                    self._export_input(role=role, query={"quote_uid": "export-series"})
                )
                self.assertFalse(result["ok"])
                self.assertIn("quote_export_pdf", result["error"])

    def test_latest_version_version_no_and_version_id_targeting(self):
        from mcp_server.tools.quote_export_pdf import quote_export_pdf

        with self._storage() as storage:
            first = self._save_quote(
                self._quote_result("export-version-001", product_name="Version One")
            )
            self._save_quote(
                self._quote_result("export-other-001", product_name="Other"),
                quote_uid="other-export",
            )
            second = self._save_quote(
                self._quote_result("export-version-002", product_name="Version Two")
            )
            self._approve_quote(storage, "export-series")
            latest = quote_export_pdf(self._export_input(query={"quote_uid": "export-series", "dry_run": True}))
            version_one = quote_export_pdf(
                self._export_input(query={"quote_uid": "export-series", "version_no": 1, "dry_run": True})
            )
            by_version_id = quote_export_pdf(
                self._export_input(
                    query={
                        "quote_uid": "export-series",
                        "version_id": first["result"]["version_id"],
                        "dry_run": True,
                    }
                )
            )

        self.assertEqual(second["result"]["version_no"], 2)
        self.assertEqual(latest["result"]["calc_quote_id"], "export-version-002")
        self.assertEqual(latest["result"]["prefill_summary"]["product_name"], "Version Two")
        self.assertEqual(version_one["result"]["calc_quote_id"], "export-version-001")
        self.assertEqual(version_one["result"]["prefill_summary"]["product_name"], "Version One")
        self.assertEqual(by_version_id["result"]["calc_quote_id"], "export-version-001")

    def test_dry_run_for_pending_quote_returns_approval_state_and_no_file(self):
        from mcp_server.tools.quote_export_pdf import quote_export_pdf

        with self._storage():
            self._save_quote(self._quote_result("export-dry-run-001"))
            result = quote_export_pdf(
                self._export_input(query={"quote_uid": "export-series", "dry_run": True})
            )

        self.assertTrue(result["ok"])
        export = result["result"]
        self.assertTrue(export["dry_run"])
        self.assertFalse(export["can_export"])
        self.assertEqual(export["approval_status"], "pending")
        self.assertEqual(export["approval_note"], "")
        self.assertEqual(export["missing_fields"], [])
        self.assertNotIn("file_path", export)

    def test_dry_run_for_approved_quote_can_export_without_file(self):
        from mcp_server.tools.quote_export_pdf import quote_export_pdf

        with self._storage() as storage:
            saved = self._save_quote(self._quote_result("export-dry-run-approved-001"))
            self._approve_quote(storage, saved["result"]["quote_uid"])
            result = quote_export_pdf(
                self._export_input(query={"quote_uid": "export-series", "dry_run": True})
            )

        self.assertTrue(result["ok"])
        export = result["result"]
        self.assertTrue(export["dry_run"])
        self.assertTrue(export["can_export"])
        self.assertEqual(export["approval_status"], "approved")
        self.assertNotIn("file_path", export)

    def test_supports_english_fob_usd_and_bilingual_modes(self):
        from mcp_server.tools.quote_export_pdf import quote_export_pdf

        with self._storage() as storage:
            self._save_quote(self._quote_result("export-fob-001", include_fob=True))
            self._approve_quote(storage, "export-series")
            english = quote_export_pdf(
                self._export_input(
                    query={"quote_uid": "export-series", "lang": "en", "dry_run": True}
                )
            )
            fob = quote_export_pdf(
                self._export_input(
                    query={
                        "quote_uid": "export-series",
                        "lang": "en",
                        "currency_mode": "fob_usd",
                        "dry_run": True,
                    }
                )
            )
            bilingual = quote_export_pdf(
                self._export_input(
                    query={"quote_uid": "export-series", "lang": "bilingual", "dry_run": True}
                )
            )

        self.assertEqual(english["result"]["export_lang"], "en")
        self.assertEqual(fob["result"]["currency_mode"], "fob_usd")
        self.assertEqual(bilingual["result"]["export_lang"], "bilingual")

    def test_does_not_recalculate_read_legacy_jsonl_or_copy_frontend_template(self):
        from mcp_server.tools.quote_export_pdf import quote_export_pdf

        with self._storage() as storage, patch("quote_engine.calculate_quote") as quote_engine, patch(
            "quotation_agent.calculator_bridge.run_calculate_quote"
        ) as bridge, patch("pathlib.Path.read_text") as read_text:
            self._save_quote(self._quote_result("export-safe-001"))
            self._approve_quote(storage, "export-series")
            result = quote_export_pdf(self._export_input(query={"quote_uid": "export-series"}))

        self.assertTrue(result["ok"])
        quote_engine.assert_not_called()
        bridge.assert_not_called()
        read_text.assert_not_called()

    def test_audit_log_records_summary_only(self):
        from mcp_server.tools.quote_export_pdf import quote_export_pdf

        with self._storage() as storage:
            saved = self._save_quote(self._quote_result("export-audit-001"))
            self._approve_quote(storage, saved["result"]["quote_uid"])
            result = quote_export_pdf(
                self._export_input(query={"quote_uid": "export-series", "lang": "cn"})
            )

        self.assertTrue(result["ok"])
        records = [
            json.loads(line)
            for line in self.audit_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        latest = records[-1]
        serialized = json.dumps(latest, ensure_ascii=False)
        self.assertEqual(latest["tool"], "quote_export_pdf")
        self.assertEqual(latest["quote_uid"], "export-series")
        self.assertEqual(latest["export_lang"], "cn")
        self.assertNotIn("quote_result", serialized)
        self.assertNotIn("detail_rows", serialized)
        self.assertNotIn("quote_json", serialized)
        self.assertNotIn("rows", serialized)


if __name__ == "__main__":
    unittest.main()
