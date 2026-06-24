from __future__ import annotations

import unittest

from quote_mode_validation import (
    build_source_summary,
    normalize_quote_mode,
    normalize_source,
    validate_quote_payload_for_mode,
)


class QuoteModeValidationTest(unittest.TestCase):
    def test_normalizes_quote_mode_and_source_aliases(self) -> None:
        self.assertEqual(normalize_quote_mode("production"), "production_mode")
        self.assertEqual(normalize_quote_mode("formal"), "production_mode")
        self.assertEqual(normalize_quote_mode("draft"), "draft_mode")
        self.assertEqual(normalize_quote_mode("demo"), "demo_mode")
        self.assertEqual(normalize_quote_mode("unknown"), "draft_mode")

        self.assertEqual(normalize_source("manual"), "user_input")
        self.assertEqual(normalize_source("sheet"), "uploaded_bom")
        self.assertEqual(normalize_source("kb"), "price_kb")
        self.assertEqual(normalize_source("override"), "approved_rule")
        self.assertEqual(normalize_source("ai"), "ai_estimate")
        self.assertEqual(normalize_source("demo"), "default_demo")
        self.assertEqual(normalize_source("not-real"), "")

    def test_demo_mode_allows_default_demo_and_default_line_items(self) -> None:
        payload = {
            "quote_mode": "demo_mode",
            "default_line_items": True,
            "items": [
                {
                    "name": "demo fabric",
                    "usage": "1m",
                    "unit_price": "10",
                    "amount": 10,
                    "source": "default_demo",
                }
            ],
            "quantities": [300, 500, 1000],
            "mold_fee": 1000,
            "mold_fee_source": "default_demo",
        }

        out = validate_quote_payload_for_mode(payload)

        self.assertEqual(out["quote_mode"], "demo_mode")
        self.assertEqual(out["validation_status"], "passed")
        self.assertEqual(out["validation_errors"], [])
        self.assertEqual(out["source_summary"]["default_demo"], 2)

    def test_draft_mode_allows_ai_estimate_but_requires_review(self) -> None:
        payload = {
            "quote_mode": "draft_mode",
            "items": [
                {
                    "name": "zipper",
                    "usage": "1pc",
                    "unit_price": "3",
                    "amount": 3,
                    "source": "ai_estimate",
                }
            ],
            "quantities": [500],
            "processing_fee": 12,
            "processing_fee_source": "user_input",
        }

        out = validate_quote_payload_for_mode(payload)

        self.assertEqual(out["validation_status"], "review_required")
        self.assertEqual(out["validation_errors"], [])
        self.assertEqual(out["source_summary"]["ai_estimate"], 1)
        self.assertEqual(out["source_summary"]["user_input"], 1)

    def test_production_mode_blocks_missing_items_and_quantities(self) -> None:
        out = validate_quote_payload_for_mode({}, quote_mode="production_mode")

        self.assertEqual(out["validation_status"], "blocked")
        self.assert_error_codes(
            out,
            {
                "items_missing",
                "quantities_missing",
            },
        )

    def test_production_mode_blocks_default_demo_ai_and_missing_amount_sources(self) -> None:
        payload = {
            "quote_mode": "production_mode",
            "default_line_items": True,
            "items": [
                {
                    "name": "demo fabric",
                    "usage": "1m",
                    "unit_price": "10",
                    "amount": 10,
                    "source": "default_demo",
                },
                {
                    "name": "estimated zipper",
                    "usage": "1pc",
                    "usage_source": "user_input",
                    "unit_price": "3",
                    "unit_price_source": "ai_estimate",
                    "amount": 3,
                    "amount_source": "ai_estimate",
                    "source": "ai_estimate",
                },
                {
                    "name": "missing source row",
                    "usage": "1pc",
                    "unit_price": "2",
                    "amount": 2,
                    "source": "uploaded_bom",
                },
            ],
            "quantities": [500],
            "mold_fee": 1000,
            "processing_fee": 12,
            "processing_fee_source": "user_input",
            "system_overhead": 4,
            "system_overhead_source": "approved_rule",
            "gross_margin_rate": 0.35,
            "gross_margin_rate_source": "user_input",
            "fob_addition": 4,
        }

        out = validate_quote_payload_for_mode(payload)

        self.assertEqual(out["validation_status"], "blocked")
        self.assert_error_codes(
            out,
            {
                "default_line_items_not_allowed",
                "default_demo_not_allowed",
                "ai_estimate_not_allowed",
                "amount_field_source_missing",
            },
        )
        paths = {err["path"] for err in out["validation_errors"]}
        self.assertIn("items[2].usage", paths)
        self.assertIn("mold_fee", paths)
        self.assertIn("fob_addition", paths)

    def test_build_source_summary_reads_payload_and_result_rows(self) -> None:
        payload = {
            "items": [
                {"source": "manual", "unit_price_source": "kb"},
                {"source": "ai"},
            ],
            "processing_fee_source": "user_input",
        }
        result = {
            "detail_rows": [
                {"source": "approved_rule"},
                {"source": "default_demo"},
            ]
        }

        summary = build_source_summary(payload, result=result)

        self.assertEqual(summary["user_input"], 2)
        self.assertEqual(summary["price_kb"], 1)
        self.assertEqual(summary["ai_estimate"], 1)
        self.assertEqual(summary["approved_rule"], 1)
        self.assertEqual(summary["default_demo"], 1)

    def assert_error_codes(self, out: dict, expected: set[str]) -> None:
        self.assertTrue(expected.issubset({err["code"] for err in out["validation_errors"]}))


if __name__ == "__main__":
    unittest.main()
