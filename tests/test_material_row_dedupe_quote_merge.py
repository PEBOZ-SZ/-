from __future__ import annotations

import unittest

from material_row_dedupe import merge_duplicate_quote_material_rows


class MergeDuplicateQuoteMaterialRowsTest(unittest.TestCase):
    def test_exact_duplicate_rows_are_merged(self) -> None:
        rows = [
            {
                "name": " FJ-150D记忆布 ",
                "spec": "45*25*2",
                "usage": "0.45码",
                "unit_price": "7.8元/码",
                "amount": 3.51,
                "calc_note": "主料按裁片面积表合计",
                "section_key": "C",
            },
            {
                "name": "FJ-150D记忆布",
                "spec": "45*25*2",
                "usage": "0.45码",
                "unit_price": "7.8元/码",
                "amount": 3.51,
                "calc_method": "主料按裁片面积表合计",
                "area": "C",
            },
        ]

        merged = merge_duplicate_quote_material_rows(rows)

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["usage"], "0.9码")
        self.assertAlmostEqual(float(merged[0]["amount"]), 7.02)
        self.assertEqual(merged[0]["merged_duplicate_count"], 2)
        self.assertEqual(merged[0]["source_row_indices"], [0, 1])

    def test_same_name_different_spec_is_not_merged(self) -> None:
        rows = [
            {"name": "FJ-150D记忆布", "spec": "45*25*2", "usage": "0.45码", "unit_price": "7.8元/码"},
            {"name": "FJ-150D记忆布", "spec": "50*25*2", "usage": "0.45码", "unit_price": "7.8元/码"},
        ]

        merged = merge_duplicate_quote_material_rows(rows)

        self.assertEqual(len(merged), 2)
        self.assertTrue(all(row.get("needs_manual_confirm") for row in merged))
        self.assertIn("同名不同规格/单价", merged[0]["recognition_reason"])

    def test_same_name_different_unit_price_is_not_merged(self) -> None:
        rows = [
            {"name": "5#树脂拉链", "spec": "长25CM", "usage": "1.5米", "unit_price": "2元/米"},
            {"name": "5#树脂拉链", "spec": "长25CM", "usage": "1.5米", "unit_price": "3元/米"},
        ]

        merged = merge_duplicate_quote_material_rows(rows)

        self.assertEqual(len(merged), 2)
        self.assertTrue(all(row.get("needs_manual_confirm") for row in merged))

    def test_parseable_usage_is_summed(self) -> None:
        rows = [
            {"name": "5#树脂拉链", "spec": "长25CM", "usage": "1.5米", "unit_price": "2元/米", "amount": 3},
            {"name": "5#树脂拉链", "spec": "长25CM", "usage": "1.5米", "unit_price": "2元/米", "amount": 3},
            {"name": "5#树脂拉链", "spec": "长25CM", "usage": "1.5米", "unit_price": "2元/米", "amount": 3},
        ]

        merged = merge_duplicate_quote_material_rows(rows)

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["usage"], "4.5米")
        self.assertAlmostEqual(float(merged[0]["amount"]), 9.0)

    def test_unparseable_usage_keeps_original_and_adds_remark(self) -> None:
        rows = [
            {"name": "织带", "spec": "25mm", "usage": "按实耗", "unit_price": "1元/米", "remark": "A"},
            {"name": "织带", "spec": "25mm", "usage": "复核后定", "unit_price": "1元/米", "remark": "A"},
        ]

        merged = merge_duplicate_quote_material_rows(rows)

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["usage"], "按实耗")
        self.assertIn("由 2 条同名行合并", merged[0]["remark"])
        self.assertIn("按实耗", merged[0]["remark"])
        self.assertIn("复核后定", merged[0]["remark"])


if __name__ == "__main__":
    unittest.main()
