from __future__ import annotations

import unittest

from quote_engine import calculate_quote


class QuoteEngineQuoteModeTest(unittest.TestCase):
    def test_production_mode_missing_items_is_blocked(self) -> None:
        out = calculate_quote(
            {
                "quote_mode": "production_mode",
                "quantities": [500],
                "fob_addition": 4,
                "fob_addition_source": "user_input",
            }
        )

        self.assertEqual(out["quote_mode"], "production_mode")
        self.assertEqual(out["validation_status"], "blocked")
        self.assert_error_codes(out, {"items_missing"})
        self.assertFalse(out.get("quote_ready", True))
        self.assertNotIn("tiers", out)

    def test_production_mode_non_list_items_is_blocked(self) -> None:
        out = calculate_quote(
            {
                "quote_mode": "production_mode",
                "items": "not-a-list",
                "quantities": [500],
                "fob_addition": 4,
                "fob_addition_source": "user_input",
            }
        )

        self.assertEqual(out["validation_status"], "blocked")
        self.assert_error_codes(out, {"items_not_list"})
        self.assertNotIn("detail_rows", out)

    def test_production_mode_missing_quantities_is_blocked(self) -> None:
        out = calculate_quote(
            {
                "quote_mode": "production_mode",
                "items": [self.production_item()],
                "fob_addition": 4,
                "fob_addition_source": "user_input",
            }
        )

        self.assertEqual(out["validation_status"], "blocked")
        self.assert_error_codes(out, {"quantities_missing"})
        self.assertNotIn("tiers", out)

    def test_production_mode_does_not_use_default_line_items(self) -> None:
        out = calculate_quote(
            {
                "quote_mode": "production_mode",
                "quantities": [300],
                "fob_addition": 4,
                "fob_addition_source": "user_input",
            }
        )

        self.assertEqual(out["validation_status"], "blocked")
        self.assert_error_codes(out, {"items_missing"})
        self.assertEqual(out.get("source_summary", {}), {"user_input": 1})

    def test_production_mode_missing_fob_addition_is_blocked(self) -> None:
        out = calculate_quote(
            {
                "quote_mode": "production_mode",
                "items": [self.production_item()],
                "quantities": [500],
                "mold_fee": 1000,
                "mold_fee_source": "user_input",
                "processing_fee": 12,
                "processing_fee_source": "user_input",
                "system_overhead": 4,
                "system_overhead_source": "user_input",
                "gross_margin_rate": 0.35,
                "gross_margin_rate_source": "user_input",
            }
        )

        self.assertEqual(out["validation_status"], "blocked")
        self.assert_error_codes(out, {"fob_addition_missing"})
        self.assertNotIn("tiers", out)

    def test_demo_mode_can_use_default_line_items_with_default_demo_source(self) -> None:
        out = calculate_quote({"quote_mode": "demo_mode"})

        self.assertEqual(out["quote_mode"], "demo_mode")
        self.assertEqual(out["validation_status"], "passed")
        self.assertEqual(out["validation_errors"], [])
        self.assertTrue(out["detail_rows"])
        self.assertTrue(all(row["source"] == "default_demo" for row in out["detail_rows"]))
        self.assertEqual(out["settings_sources"]["mold_fee"], "default_demo")
        self.assertEqual(out["settings_sources"]["fob_addition"], "default_demo")
        self.assertGreater(out["source_summary"]["default_demo"], 1)

    def test_draft_mode_ai_estimate_returns_review_required(self) -> None:
        out = calculate_quote(
            {
                "quote_mode": "draft_mode",
                "items": [
                    {
                        "name": "estimated zipper",
                        "usage": "1pc",
                        "unit_price": "3",
                        "amount": 3,
                        "source": "ai_estimate",
                        "unit_price_ai": True,
                        "amount_ai": True,
                    }
                ],
                "quantities": [500],
            }
        )

        self.assertEqual(out["quote_mode"], "draft_mode")
        self.assertEqual(out["validation_status"], "review_required")
        self.assertEqual(out["validation_errors"], [])
        self.assertGreaterEqual(out["source_summary"]["ai_estimate"], 1)
        self.assertIn("tiers", out)

    def test_quote_params_order_quantities_override_frontend_default_one(self) -> None:
        out = calculate_quote(
            {
                "quote_mode": "draft_mode",
                "items": [self.production_item()],
                "quantities": [1],
                "quote_params": {"F": {"\u6570\u91cf1": "5000", "\u6570\u91cf2": "10000"}},
                "mold_fee": 2000,
                "processing_fee": 15,
                "system_overhead": 4,
                "gross_margin_rate": 0.45,
            }
        )

        tier = out["tiers"][0]
        self.assertEqual(tier["quantity"], 5000)
        self.assertEqual(tier["mold_share"], 0.4)

    def test_quote_params_order_quantities_drop_plain_one_from_requirement_fields(self) -> None:
        out = calculate_quote(
            {
                "quote_mode": "draft_mode",
                "items": [self.production_item()],
                "quantities": [5000, 10000, 1],
                "quote_params": {"F": {"\u6570\u91cf1": "5000", "\u6570\u91cf2": "10000"}},
                "requirement_fields": {
                    "\u6570\u91cf1": "2\u7247 / 5000",
                    "\u6570\u91cf2": "1\u4e2a / 10000",
                    "\u6570\u91cf3": "1",
                },
                "mold_fee": 2000,
                "processing_fee": 15,
                "system_overhead": 4,
                "gross_margin_rate": 0.45,
            }
        )

        self.assertEqual([tier["quantity"] for tier in out["tiers"]], [5000, 10000])

    def production_item(self) -> dict:
        return {
            "name": "fabric",
            "usage": "1m",
            "usage_source": "uploaded_bom",
            "unit_price": "10",
            "unit_price_source": "price_kb",
            "amount": 10,
            "amount_source": "price_kb",
            "source": "uploaded_bom",
        }

    def assert_error_codes(self, out: dict, expected: set[str]) -> None:
        self.assertTrue(expected.issubset({err["code"] for err in out["validation_errors"]}))


if __name__ == "__main__":
    unittest.main()
