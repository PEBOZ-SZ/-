"""batch_quote_audit 核心检查逻辑测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from batch_quote_audit import (
    audit_detail_rows,
    audit_quote_result,
    audit_tiers,
    compute_expected_amount,
    list_xlsx_files,
    write_audit_report,
)


class BatchQuoteAuditTest(unittest.TestCase):
    def _meta(self) -> dict:
        return {
            "file_path": "D:/test/sample.xlsx",
            "file_name": "sample.xlsx",
            "sheet_name": "Sheet1",
            "product_name": "测试包",
        }

    def test_amount_usage_price_match_passes(self) -> None:
        rows = [{"name": "420D尼龙", "usage": "1.5码", "unit_price": "20元/码", "amount": 30.0}]
        issues = audit_detail_rows(rows, meta=self._meta())
        mismatch = [i for i in issues if i.issue_code == "amount_usage_price_mismatch"]
        self.assertEqual(mismatch, [])
        self.assertAlmostEqual(compute_expected_amount("1.5码", "20元/码"), 30.0)

    def test_amount_mismatch_generates_issue(self) -> None:
        rows = [{"name": "420D尼龙", "usage": "1.5码", "unit_price": "20元/码", "amount": 40.0}]
        issues = audit_detail_rows(rows, meta=self._meta())
        codes = {i.issue_code for i in issues}
        self.assertIn("amount_usage_price_mismatch", codes)
        self.assertTrue(any(i.severity in {"red", "yellow"} for i in issues))

    def test_material_total_detail_sum_mismatch(self) -> None:
        result = {
            "product_name": "测试包",
            "material_total": 100.0,
            "detail_rows": [
                {"name": "面料A", "usage": "1码", "unit_price": "10元/码", "amount": 30.0},
                {"name": "面料B", "usage": "1码", "unit_price": "20元/码", "amount": 50.0},
            ],
            "summary_rows": [{"name": "物料合计", "amount": 100.0}],
            "settings": {
                "mold_fee": 0,
                "processing_fee": 5,
                "system_overhead": 4,
                "fob_addition_per_piece": 0,
            },
            "include_fob": False,
            "tiers": [
                {
                    "quantity": 300,
                    "mold_share": 0,
                    "processing_fee": 5,
                    "system_overhead_applied": 4,
                    "cost_before_margin": 89.0,
                    "total_cost": 89.0,
                    "margin_rate": 0.35,
                    "exw_price": round(89 / 0.65, 2),
                }
            ],
        }
        tier_issues = audit_tiers(result, {"product_name": "测试包"})
        codes = {i.issue_code for i in tier_issues}
        self.assertIn("material_total_detail_sum_mismatch", codes)

    def test_ai_fields_generate_yellow_issue(self) -> None:
        rows = [
            {
                "name": "里布",
                "usage": "0.8码",
                "unit_price": "12元/码",
                "amount": 9.6,
                "unit_price_ai": True,
                "pricing_review_required": True,
                "recognition_status": "candidate_review",
            }
        ]
        issues = audit_detail_rows(rows, meta=self._meta())
        self.assertTrue(any(i.issue_code == "ai_or_manual_review_required" for i in issues))
        self.assertTrue(all(i.severity == "yellow" for i in issues if i.issue_code == "ai_or_manual_review_required"))

    def test_unit_conflict_generates_red_issue(self) -> None:
        from badge_unit_guard import apply_badge_unit_guard_to_row

        row = {"name": "PU拉牌", "usage": "1码", "unit_price": "24.5/码", "amount": 24.5}
        guarded = apply_badge_unit_guard_to_row(row)
        issues = audit_detail_rows([guarded], meta=self._meta())
        self.assertTrue(any(i.issue_code == "unit_usage_price_conflict" and i.severity == "red" for i in issues))

    def test_empty_directory_is_friendly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            files = list_xlsx_files(Path(tmp))
            self.assertEqual(files, [])

    def test_write_audit_report_csv(self) -> None:
        from batch_quote_audit import AuditIssue, AuditSummary

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "report.csv"
            summary = AuditSummary(file_name="a.xlsx", severity="green")
            issue = AuditIssue(file_name="a.xlsx", issue_code="ok", issue_message="无问题", severity="green")
            path = write_audit_report([summary], [issue], out, fmt="csv")
            self.assertTrue(path.exists())

    def test_audit_quote_result_reference_gap(self) -> None:
        result = {
            "product_name": "测试包",
            "material_total": 50.0,
            "detail_rows": [{"name": "面料", "usage": "1码", "unit_price": "50元/码", "amount": 50.0}],
            "summary_rows": [{"name": "物料合计", "amount": 50.0}],
            "settings": {"mold_fee": 0, "processing_fee": 5, "system_overhead": 4, "fob_addition_per_piece": 0},
            "include_fob": False,
            "tiers": [
                {
                    "quantity": 300,
                    "mold_share": 0,
                    "processing_fee": 5,
                    "system_overhead_applied": 4,
                    "cost_before_margin": 59.0,
                    "total_cost": 59.0,
                    "margin_rate": 0.35,
                    "exw_price": round(59 / 0.65, 2),
                }
            ],
        }
        context = {
            **self._meta(),
            "scan_rows": [["系统算出成本13.73元"]],
        }
        payload = {"reference_prices": []}
        audit = audit_quote_result(result, context, payload)
        self.assertTrue(any(i.issue_code == "reference_cost_gap" for i in audit.issues))


if __name__ == "__main__":
    unittest.main()
