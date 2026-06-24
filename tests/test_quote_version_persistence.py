from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import quote_upload_storage as storage


class QuoteVersionPersistenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self.tmp.cleanup)
        self.old_db_path = storage.DB_PATH
        self.old_data_dir = storage.DATA_DIR
        self.old_uploads_dir = storage.UPLOADS_DIR
        root = Path(self.tmp.name)
        storage.DATA_DIR = root
        storage.UPLOADS_DIR = root / "uploads"
        storage.DB_PATH = root / "quotes.db"
        self.addCleanup(self._restore_paths)

    def _restore_paths(self) -> None:
        storage.DB_PATH = self.old_db_path
        storage.DATA_DIR = self.old_data_dir
        storage.UPLOADS_DIR = self.old_uploads_dir

    def test_schema_init_is_idempotent(self) -> None:
        storage.init_quote_storage()
        storage.init_quote_storage()

        with sqlite3.connect(storage.DB_PATH) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }

        self.assertIn("quote_versions", tables)
        self.assertIn("quote_sessions", tables)
        self.assertIn("quote_patches", tables)
        self.assertIn("quote_audit_logs", tables)

    def test_quote_versions_store_structured_fields_and_increment_versions(self) -> None:
        quote1 = self.quote_result("calc-1")
        storage.save_quote_calculation(
            quote_uid="series-1",
            calc_quote_id="calc-1",
            sheet_original_display_name="first.xlsx",
            uploaded_sheet=None,
            quote_result=quote1,
            structured_input={"items": [{"name": "fabric"}], "quantities": [500]},
            quote_mode="production_mode",
            validation_status="passed",
            source_summary={"uploaded_bom": 1, "price_kb": 1},
        )
        storage.save_quote_calculation(
            quote_uid="series-1",
            calc_quote_id="calc-2",
            sheet_original_display_name="second.xlsx",
            uploaded_sheet=None,
            quote_result=self.quote_result("calc-2"),
            structured_input={"items": [{"name": "fabric v2"}], "quantities": [800]},
            quote_mode="production_mode",
            validation_status="passed",
            base_version_no=1,
            base_calc_quote_id="calc-1",
            patch_id="patch-1",
            source_summary={"user_input": 1},
        )

        latest = storage.resolve_quote_version_target("series-1")
        self.assertEqual(latest["version_no"], 2)
        self.assertEqual(latest["calc_quote_id"], "calc-2")

        obj = storage.load_quote_version_object("series-1", 2)
        structured = storage.load_quote_version_structured_input("series-1", 2)

        self.assertEqual(obj["quote_id"], "calc-2")
        self.assertEqual(structured["quantities"], [800])
        self.assertEqual(latest["base_version_no"], 1)
        self.assertEqual(latest["base_calc_quote_id"], "calc-1")
        self.assertEqual(latest["patch_id"], "patch-1")
        self.assertEqual(latest["source_summary"], {"user_input": 1})

    def test_quote_patches_and_audit_logs_are_saved(self) -> None:
        storage.init_quote_storage()

        patch = storage.save_quote_patch(
            patch_id="patch-committed",
            quote_series_uid="series-2",
            base_calc_quote_id="calc-base",
            base_version_no=1,
            new_calc_quote_id="calc-new",
            new_version_no=2,
            patch_type="quantity",
            patch_json={"old": 300, "new": 500},
            status="committed",
            created_by="tester",
        )
        audit = storage.save_quote_audit_log(
            quote_series_uid="series-2",
            calc_quote_id="calc-new",
            version_no=2,
            event_type="quote_patch_committed",
            event_payload={"patch_id": "patch-committed"},
        )

        with sqlite3.connect(storage.DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            patch_row = conn.execute(
                "SELECT * FROM quote_patches WHERE patch_id = ?",
                ("patch-committed",),
            ).fetchone()
            audit_row = conn.execute(
                "SELECT * FROM quote_audit_logs WHERE audit_id = ?",
                (audit["audit_id"],),
            ).fetchone()

        self.assertEqual(patch["status"], "committed")
        self.assertEqual(dict(patch_row)["new_version_no"], 2)
        self.assertEqual(dict(audit_row)["event_type"], "quote_patch_committed")

    def quote_result(self, quote_id: str) -> dict:
        return {
            "quote_id": quote_id,
            "product_name": "Test Bag",
            "material_total": 10.0,
            "quote_mode": "production_mode",
            "validation_status": "passed",
            "source_summary": {"uploaded_bom": 1},
            "tiers": [{"quantity": 500, "cost_before_margin": 20.0}],
            "detail_rows": [
                {
                    "name": "fabric",
                    "spec": "-",
                    "usage": "1m",
                    "unit_price": "10",
                    "amount": 10,
                    "amount_text": "10.00",
                    "source": "uploaded_bom",
                }
            ],
        }


if __name__ == "__main__":
    unittest.main()
