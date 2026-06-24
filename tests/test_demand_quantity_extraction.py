from __future__ import annotations

import unittest

from demand_parser import (
    _extract_implicit_quantity_section,
    _extract_order_quantity_value,
    _extract_quantities,
)


class DemandQuantityExtractionTest(unittest.TestCase):
    def test_slash_suffix_is_order_quantity_not_piece_count(self) -> None:
        self.assertEqual(_extract_order_quantity_value("2片 / 5000"), 5000)
        self.assertEqual(_extract_order_quantity_value("1个 / 10000"), 10000)

    def test_plain_piece_count_is_not_used_as_order_quantity(self) -> None:
        self.assertIsNone(_extract_order_quantity_value("3片"))
        self.assertIsNone(_extract_order_quantity_value("1PCS"))

    def test_extract_quantities_uses_order_quantity_values(self) -> None:
        out = _extract_quantities(
            {
                "数量1": "2片 / 5000",
                "数量2": "1个 / 10000",
                "数量3": "1片",
            }
        )

        self.assertEqual(out, (5000, 10000))

    def test_material_piece_quantity_headers_are_not_order_tiers(self) -> None:
        rows = [
            ["类型", "主材料规格", "对应核算尺寸", "数量", "部位裁片1", "尺寸1", "数量1", "部位裁片2", "尺寸2", "数量2"],
            ["面料1", "FJ-150D记忆布", "45*25*23CM", "1", "包身主片", "45*37CM", "2", "底部仓", "45*25*10CM", "1"],
            ["数量1", "数量2"],
            ["5000", "10000"],
        ]

        self.assertEqual(_extract_implicit_quantity_section(rows), {"数量1": "5000", "数量2": "10000"})
        self.assertEqual(_extract_quantities({}, rows=rows), (5000, 10000))


class DemandQuantityExtractionUnicodeTest(unittest.TestCase):
    def test_real_chinese_slash_suffix_is_order_quantity_not_piece_count(self) -> None:
        self.assertEqual(_extract_order_quantity_value("2\u7247 / 5000"), 5000)
        self.assertEqual(_extract_order_quantity_value("1\u4e2a / 10000"), 10000)

    def test_real_chinese_plain_piece_count_is_not_used_as_order_quantity(self) -> None:
        self.assertIsNone(_extract_order_quantity_value("3\u7247"))
        self.assertIsNone(_extract_order_quantity_value("1\u4e2a"))

    def test_extract_quantities_accepts_real_chinese_quantity_keys(self) -> None:
        out = _extract_quantities(
            {
                "\u6570\u91cf1": "2\u7247 / 5000",
                "\u6570\u91cf2": "1\u4e2a / 10000",
                "\u6570\u91cf3": "1\u7247",
            }
        )

        self.assertEqual(out, (5000, 10000))

    def test_extract_quantities_accepts_canonical_quantity_keys(self) -> None:
        out = _extract_quantities(
            {
                "quantity_1": "2\u7247 / 5000",
                "quantity_2": "1\u4e2a / 10000",
                "quantity_3": "1\u7247",
            }
        )

        self.assertEqual(out, (5000, 10000))


if __name__ == "__main__":
    unittest.main()
