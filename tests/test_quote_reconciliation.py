from __future__ import annotations

import unittest

from quote_reconciliation import RECONCILIATION_CATEGORIES, reconcile_quotes


class QuoteReconciliationTest(unittest.TestCase):
    def test_returns_all_required_categories_and_passes_within_default_tolerance(self) -> None:
        manual = {
            "reconciliation_items": {
                "主料": 100,
                "里布": 20,
                "最终单价": 200,
            }
        }
        system = {
            "reconciliation_items": {
                "主料": 102,
                "里布": 20.4,
                "最终单价": 204,
            }
        }

        report = reconcile_quotes(manual, system)

        self.assertTrue(report["within_tolerance"])
        self.assertAlmostEqual(report["total_gap_pct"], 2.0)
        self.assertEqual([item["category"] for item in report["items"]], list(RECONCILIATION_CATEGORIES))
        main = self.item(report, "主料")
        self.assertEqual(main["manual_amount"], 100.0)
        self.assertEqual(main["system_amount"], 102.0)
        self.assertEqual(main["gap_amount"], 2.0)
        self.assertAlmostEqual(main["gap_pct"], 2.0)
        self.assertTrue(main["reason_hint"])
        self.assertEqual(report["blocking_reasons"], [])

    def test_marks_out_of_tolerance_when_gap_exceeds_three_percent(self) -> None:
        report = reconcile_quotes(
            {"reconciliation_items": {"最终单价": 100}},
            {"reconciliation_items": {"最终单价": 105}},
        )

        self.assertFalse(report["within_tolerance"])
        self.assertAlmostEqual(report["total_gap_pct"], 5.0)
        final_price = self.item(report, "最终单价")
        self.assertFalse(final_price["within_tolerance"])
        self.assertIn("超过", final_price["reason_hint"])

    def test_blocks_formal_reconciliation_when_system_has_ai_or_default_demo_amount_sources(self) -> None:
        system = {
            "detail_rows": [
                {"name": "zipper", "amount": 3, "source": "ai_estimate"},
                {"name": "demo fabric", "amount": 10, "source": "default_demo"},
            ],
            "source_summary": {"ai_estimate": 1, "default_demo": 1},
        }

        report = reconcile_quotes({"reconciliation_items": {"最终单价": 100}}, system)

        self.assertFalse(report["within_tolerance"])
        self.assertTrue(any("ai_estimate" in reason for reason in report["blocking_reasons"]))
        self.assertTrue(any("default_demo" in reason for reason in report["blocking_reasons"]))

    def test_can_extract_amounts_from_detail_rows_and_settings(self) -> None:
        manual = {
            "detail_rows": [
                {"name": "主面料", "amount": 100},
                {"name": "拉链", "amount": 5},
                {"name": "包装袋", "amount": 1},
            ],
            "settings": {"gross_margin_rate": 0.35},
            "tiers": [{"quantity": 500, "exw_price": 200, "fob_price": 204}],
        }
        system = {
            "detail_rows": [
                {"name": "主面料", "amount": 106},
                {"name": "拉链", "amount": 5.2},
                {"name": "包装袋", "amount": 1.1},
            ],
            "settings": {"gross_margin_rate": 0.38},
            "tiers": [{"quantity": 500, "exw_price": 208, "fob_price": 212}],
        }

        report = reconcile_quotes(manual, system)

        self.assertEqual(self.item(report, "主料")["manual_amount"], 100.0)
        self.assertEqual(self.item(report, "拉链")["manual_amount"], 5.0)
        self.assertEqual(self.item(report, "包装")["manual_amount"], 1.0)
        self.assertEqual(self.item(report, "毛利率")["manual_amount"], 0.35)
        self.assertEqual(self.item(report, "EXW")["system_amount"], 208.0)
        self.assertEqual(self.item(report, "FOB")["system_amount"], 212.0)

    def item(self, report: dict, category: str) -> dict:
        for item in report["items"]:
            if item["category"] == category:
                return item
        raise AssertionError(f"missing category: {category}")


if __name__ == "__main__":
    unittest.main()
