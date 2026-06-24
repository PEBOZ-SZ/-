"""结构确认用户补丁合并：remark / section_key / included_in_quote。"""

from __future__ import annotations

import unittest

from server import merge_structure_confirmation_user_items


class MergeStructureConfirmationUserItemsTest(unittest.TestCase):
    def test_merges_remark_section_and_included_flags(self) -> None:
        base = [
            {
                "name": "外料",
                "spec": "10*20",
                "usage": "1.2",
                "unit_price": "10",
                "calc_note": "面积",
                "amount_in_cost": True,
            }
        ]
        patch = [
            {
                "index": 0,
                "remark": "业务员备注",
                "section_key": "C",
                "included_in_quote": False,
            }
        ]
        merged = merge_structure_confirmation_user_items(base, patch)
        self.assertEqual(len(merged), 1)
        row = merged[0]
        self.assertEqual(row.get("remark"), "业务员备注")
        self.assertEqual(row.get("section_key"), "C")
        self.assertEqual(row.get("area"), "C")
        self.assertFalse(row.get("amount_in_cost"))
        self.assertTrue(row.get("exclude_from_cost"))


if __name__ == "__main__":
    unittest.main()
