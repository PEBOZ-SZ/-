from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import local_quote_patch
import quote_upload_storage as storage


class LocalQuotePatchRevisionTest(unittest.TestCase):
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

    def test_trial_preview_does_not_write_quote_versions(self) -> None:
        base_payload = self.structured_input([300])
        base_result = {"tiers": [{"quantity": 300, "total_cost": 20.0}]}

        with patch.object(local_quote_patch, "parse_local_patch", return_value={"quantity": 500}):
            out = local_quote_patch.run_local_quote_trial_preview(
                sid="sid-1",
                user_message="use 500",
                session_context={
                    "currentQuoteId": "calc-A",
                    "active_quote": {
                        "quote_id": "calc-A",
                        "payload_snapshot": base_payload,
                        "last_quote_result": base_result,
                    },
                },
            )

        self.assertTrue(out["quote_ready"])
        self.assertEqual(out["metadata"]["mode"], "trial_preview")
        self.assertIn("preview_result", out)
        self.assertEqual(out["preview_result"]["tiers"][0]["quantity"], 500)

        storage.init_quote_storage()
        with sqlite3.connect(storage.DB_PATH) as conn:
            count = conn.execute("SELECT COUNT(*) FROM quote_versions").fetchone()[0]
            patch_count = conn.execute("SELECT COUNT(*) FROM quote_patches").fetchone()[0]
        self.assertEqual(count, 0)
        self.assertEqual(patch_count, 0)

    def test_commit_revision_requires_explicit_version_target(self) -> None:
        out = local_quote_patch.run_local_quote_commit_revision(
            user_message="use 500",
            quote_series_uid="series-A",
            base_version_no=None,
            base_calc_quote_id="calc-A",
        )

        self.assertFalse(out["quote_ready"])
        self.assertEqual(out["assistant_message"], "请确认要修改哪一张报价 / 哪一个版本。")

    def test_commit_revision_creates_new_version_patch_and_audit(self) -> None:
        self.save_base_quote("series-A", "calc-A", [300])

        with patch.object(local_quote_patch, "parse_local_patch", return_value={"quantity": 500}):
            out = local_quote_patch.run_local_quote_commit_revision(
                user_message="use 500",
                quote_series_uid="series-A",
                base_version_no=1,
                base_calc_quote_id="calc-A",
                created_by="tester",
            )

        self.assertTrue(out["quote_ready"])
        self.assertEqual(out["quote_series_uid"], "series-A")
        self.assertEqual(out["base_version_no"], 1)
        self.assertEqual(out["base_calc_quote_id"], "calc-A")
        self.assertEqual(out["new_version_no"], 2)
        self.assertTrue(out["new_calc_quote_id"])
        self.assertEqual(out["validation_status"], "passed")
        self.assertEqual(out["validation_errors"], [])

        structured = storage.load_quote_version_structured_input("series-A", 2)
        target = storage.resolve_quote_version_target("series-A", version_no=2)
        self.assertEqual(structured["quantities"], [500])
        self.assertEqual(target["base_version_no"], 1)
        self.assertEqual(target["base_calc_quote_id"], "calc-A")
        self.assertEqual(target["patch_id"], out["patch_id"])

        with sqlite3.connect(storage.DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            patch_row = conn.execute(
                "SELECT * FROM quote_patches WHERE patch_id = ?",
                (out["patch_id"],),
            ).fetchone()
            audit_row = conn.execute(
                "SELECT * FROM quote_audit_logs WHERE quote_series_uid = ?",
                ("series-A",),
            ).fetchone()
        self.assertEqual(dict(patch_row)["status"], "committed")
        self.assertEqual(dict(patch_row)["new_version_no"], 2)
        self.assertEqual(dict(audit_row)["event_type"], "commit_revision")

    def test_commit_revision_explicitly_modifies_a_not_recent_b(self) -> None:
        self.save_base_quote("series-A", "calc-A", [300])
        self.save_base_quote("series-B", "calc-B", [900])

        with patch.object(local_quote_patch, "parse_local_patch", return_value={"quantity": 500}):
            out = local_quote_patch.run_local_quote_commit_revision(
                user_message="use 500",
                quote_series_uid="series-A",
                base_version_no=1,
                base_calc_quote_id="calc-A",
            )

        self.assertTrue(out["quote_ready"])
        self.assertEqual(storage.resolve_quote_version_target("series-A")["version_no"], 2)
        self.assertEqual(storage.resolve_quote_version_target("series-B")["version_no"], 1)
        self.assertEqual(storage.load_quote_version_structured_input("series-B", 1)["quantities"], [900])

    def save_base_quote(self, series_uid: str, calc_id: str, quantities: list[int]) -> None:
        payload = self.structured_input(quantities)
        result = local_quote_patch.tools.calculate_local_quote(payload)
        result["quote_id"] = calc_id
        result["quote_ready"] = True
        storage.save_quote_calculation(
            quote_uid=series_uid,
            calc_quote_id=calc_id,
            sheet_original_display_name="base.xlsx",
            uploaded_sheet=None,
            quote_result=result,
            structured_input=payload,
            quote_mode="production_mode",
            validation_status=result.get("validation_status"),
            source_summary=result.get("source_summary"),
        )

    def structured_input(self, quantities: list[int]) -> dict:
        return {
            "quote_mode": "production_mode",
            "product_name": "Patch Test Bag",
            "items": [
                {
                    "name": "fabric",
                    "usage": "1m",
                    "usage_source": "uploaded_bom",
                    "unit_price": "10",
                    "unit_price_source": "price_kb",
                    "amount": 10,
                    "amount_source": "price_kb",
                    "source": "uploaded_bom",
                }
            ],
            "quantities": quantities,
            "mold_fee": 1000,
            "mold_fee_source": "user_input",
            "processing_fee": 12,
            "processing_fee_source": "user_input",
            "system_overhead": 4,
            "system_overhead_source": "user_input",
            "gross_margin_rate": 0.35,
            "gross_margin_rate_source": "user_input",
            "fob_addition": 4,
            "fob_addition_source": "user_input",
        }


if __name__ == "__main__":
    unittest.main()
