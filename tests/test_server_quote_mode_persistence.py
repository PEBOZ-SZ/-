from __future__ import annotations

import unittest
import os
from unittest.mock import patch

import server


class ServerQuoteModePersistenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self._old_strict_formal = os.environ.pop("QUOTE_STRICT_FORMAL_VALIDATION", None)

    def tearDown(self) -> None:
        if self._old_strict_formal is not None:
            os.environ["QUOTE_STRICT_FORMAL_VALIDATION"] = self._old_strict_formal
        else:
            os.environ.pop("QUOTE_STRICT_FORMAL_VALIDATION", None)

    def test_prepare_quote_mode_defaults_to_draft_and_confirmed_stays_draft_by_default(self) -> None:
        draft_payload: dict = {}
        server._prepare_quote_mode_for_calculation(draft_payload)
        self.assertEqual(draft_payload["quote_mode"], "draft_mode")

        prod_payload = {"quote_confirmed": True}
        server._prepare_quote_mode_for_calculation(prod_payload)
        self.assertEqual(prod_payload["quote_mode"], "draft_mode")

        demo_payload = {"quote_mode": "demo_mode", "quote_confirmed": True}
        server._prepare_quote_mode_for_calculation(demo_payload)
        self.assertEqual(demo_payload["quote_mode"], "demo_mode")

    def test_prepare_quote_mode_can_restore_strict_confirmed_production_with_env(self) -> None:
        os.environ["QUOTE_STRICT_FORMAL_VALIDATION"] = "1"

        prod_payload = {"quote_confirmed": True}
        server._prepare_quote_mode_for_calculation(prod_payload)
        self.assertEqual(prod_payload["quote_mode"], "production_mode")

        demo_payload = {"quote_mode": "demo_mode", "quote_confirmed": True}
        server._prepare_quote_mode_for_calculation(demo_payload)
        self.assertEqual(demo_payload["quote_mode"], "demo_mode")

    def test_production_blocked_response_is_not_persistable(self) -> None:
        response = {
            "quote_mode": "production_mode",
            "validation_status": "blocked",
            "validation_errors": [{"code": "items_missing"}],
        }

        self.assertTrue(server._quote_response_blocked_for_persistence(response))

    def test_confirmed_quote_stamps_user_sources_for_production_validation(self) -> None:
        payload = {
            "quote_confirmed": True,
            "items": [
                {
                    "name": "fabric",
                    "usage": "1m",
                    "unit_price": "10",
                    "amount": 10,
                    "source": "ai_estimate",
                    "price_source": "ai_estimate",
                    "usage_ai": True,
                    "unit_price_ai": True,
                    "amount_ai": True,
                }
            ],
            "mold_fee": 1000,
            "processing_fee": 12,
            "system_overhead": 4,
            "gross_margin_rate": 0.35,
            "include_fob": True,
        }

        server._stamp_confirmed_production_sources(payload)

        row = payload["items"][0]
        self.assertEqual(row["source"], "user_input")
        self.assertEqual(row["usage_source"], "user_input")
        self.assertEqual(row["unit_price_source"], "user_input")
        self.assertEqual(row["amount_source"], "user_input")
        self.assertEqual(row["price_source"], "manual")
        self.assertNotIn("usage_ai", row)
        self.assertEqual(payload["mold_fee_source"], "user_input")
        self.assertEqual(payload["processing_fee_source"], "user_input")
        self.assertEqual(payload["fob_addition"], 4.0)
        self.assertEqual(payload["fob_addition_source"], "approved_rule")

    def test_manual_requirement_quantities_use_order_tier_after_slash(self) -> None:
        fields = {
            "\u6570\u91cf1": "2\u7247 / 5000",
            "\u6570\u91cf2": "1\u4e2a / 10000",
            "\u6570\u91cf3": "1\u7247",
        }

        self.assertEqual(server._manual_requirement_quantities(fields), [5000, 10000])

    def test_confirmed_sheet_quote_keeps_parsed_quantities_when_frontend_omits_them(self) -> None:
        payload = {"quote_confirmed": True}
        sheet_parse_result = {"quantities": [5000, 10000]}

        server._restore_uploaded_sheet_quantities_for_confirmed_quote(payload, sheet_parse_result)

        self.assertEqual(payload["quantities"], [5000, 10000])

    def test_confirmed_sheet_quote_replaces_frontend_default_one_with_quote_params(self) -> None:
        payload = {
            "quote_confirmed": True,
            "quantities": [1],
            "quote_params": {"F": {"\u6570\u91cf1": "5000", "\u6570\u91cf2": "10000"}},
        }

        server._restore_uploaded_sheet_quantities_for_confirmed_quote(payload, None)

        self.assertEqual(payload["quantities"], [5000, 10000])

    def test_persist_quote_passes_structured_input_and_validation_metadata(self) -> None:
        calls: dict = {}
        payload = {
            "quote_mode": "production_mode",
            "items": [{"name": "fabric"}],
            "quantities": [500],
        }
        response = {
            "quote_id": "calc-1",
            "quote_mode": "production_mode",
            "validation_status": "passed",
            "source_summary": {"uploaded_bom": 1},
            "detail_rows": [],
        }

        class Handler:
            headers: dict = {}
            _cookie_sales_user_id = ""

        def fake_finalize(**kwargs):
            calls.update(kwargs)

        with patch.object(server, "wecom_enabled", return_value=False), patch.object(
            server, "_bind_local_sales_identity_for_quote", return_value=("sales-1", "Alice")
        ), patch.object(server, "finalize_quote_persistence", side_effect=fake_finalize), patch.object(
            server, "upsert_quote_chat_messages", return_value=0
        ):
            ok = server._persist_quote_with_sales_user(
                Handler(),
                series_uid="series-1",
                response=response,
                payload=payload,
                sheet_fn="quote.xlsx",
                uploaded_sheet=None,
                user_message="confirm",
            )

        self.assertTrue(ok)
        self.assertEqual(calls["quote_series_uid"], "series-1")
        self.assertEqual(calls["structured_input"], payload)
        self.assertEqual(calls["quote_mode"], "production_mode")
        self.assertEqual(calls["validation_status"], "passed")
        self.assertEqual(calls["source_summary"], {"uploaded_bom": 1})


if __name__ == "__main__":
    unittest.main()
