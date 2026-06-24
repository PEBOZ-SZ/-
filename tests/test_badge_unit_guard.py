"""PU拉牌/标牌类配件不得误按码计价。"""

from __future__ import annotations

import unittest

from badge_unit_guard import (
    BADGE_UNIT_CONFLICT_REASON,
    apply_badge_unit_guard_to_row,
    badge_accessory_unit_conflict_hints,
    try_normalize_badge_row_to_piece_pricing,
)
from material_row_validity import apply_material_validity_layer, row_is_quotable_for_cost
from quote_engine import parse_items


class BadgeUnitGuardTest(unittest.TestCase):
    def test_pu_pull_tab_yard_pricing_marked_conflict(self) -> None:
        row = {
            "name": "PU拉牌",
            "spec": "58#",
            "usage": "1码",
            "unit_price": "24.5/码",
            "amount": 24.5,
            "kb_hit": True,
            "recognition_status": "matched",
        }
        out = apply_badge_unit_guard_to_row(row)
        self.assertTrue(out.get("badge_unit_conflict"))
        self.assertEqual(out.get("recognition_status"), "candidate_review")
        self.assertTrue(out.get("exclude_from_cost"))
        self.assertNotIn("amount", out)
        hints = badge_accessory_unit_conflict_hints(out)
        self.assertTrue(hints)

    def test_piece_pricing_accepted(self) -> None:
        row = {
            "name": "PU拉牌",
            "spec": "58#",
            "usage": "1个",
            "unit_price": "2元/个",
            "amount": 2.0,
        }
        out = apply_badge_unit_guard_to_row(row)
        self.assertFalse(out.get("badge_unit_conflict"))
        self.assertTrue(row_is_quotable_for_cost(out))

    def test_normalize_from_piece_price_in_calc_note(self) -> None:
        row = {
            "name": "PU拉牌",
            "spec": "58#",
            "usage": "1码",
            "unit_price": "24.5/码",
            "calc_note": "按2元/个计",
        }
        out = try_normalize_badge_row_to_piece_pricing(row)
        self.assertIsNotNone(out)
        assert out is not None
        self.assertEqual(out.get("usage"), "1个")
        self.assertEqual(out.get("unit_price"), "2元/个")
        self.assertEqual(out.get("amount"), 2.0)

    def test_fabric_yard_pricing_unaffected(self) -> None:
        row = {
            "name": "420D尼龙",
            "usage": "1.2码",
            "unit_price": "24.5/码",
            "amount": 29.4,
        }
        out = apply_badge_unit_guard_to_row(row)
        self.assertFalse(out.get("badge_unit_conflict"))
        self.assertEqual(out.get("usage"), "1.2码")

    def test_validity_layer_blocks_yard_badge_from_quote(self) -> None:
        rows = apply_material_validity_layer(
            [
                {
                    "name": "PU拉牌",
                    "spec": "58#",
                    "usage": "1码",
                    "unit_price": "24.5/码",
                    "amount": 24.5,
                    "kb_hit": True,
                }
            ]
        )
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].get("badge_unit_conflict"))
        self.assertFalse(row_is_quotable_for_cost(rows[0]))
        items = parse_items(rows)
        self.assertEqual(len(items), 0)

    def test_user_fixed_piece_pricing_parsed_into_quote(self) -> None:
        rows = apply_material_validity_layer(
            [
                {
                    "name": "PU拉牌",
                    "spec": "58#",
                    "usage": "1个",
                    "unit_price": "2元/个",
                    "amount": 2.0,
                }
            ]
        )
        items = parse_items(rows)
        self.assertEqual(len(items), 1)
        self.assertAlmostEqual(items[0].amount, 2.0)

    def test_conflict_reason_text(self) -> None:
        self.assertIn("个", BADGE_UNIT_CONFLICT_REASON)
        self.assertIn("码", BADGE_UNIT_CONFLICT_REASON)


if __name__ == "__main__":
    unittest.main()
