from __future__ import annotations

import unittest

from material_piece_summary import build_material_display_rows


class NonAreaAccessoryDisplayTest(unittest.TestCase):
    def test_grouped_zipper_and_puller_show_count_not_missing_piece_count(self) -> None:
        quote = {
            "materials_detail_rows": [
                {
                    "type": "配件/辅料",
                    "standard_name_code": "5#树脂拉链",
                    "calculation_size": "长25CM",
                    "piece_part": "3#尼龙拉链",
                    "piece_size": "长45CM",
                    "piece_quantity": "数量1",
                    "quantity": "数量1",
                    "source": "excel",
                },
                {
                    "type": "配件/辅料",
                    "standard_name_code": "5#树脂拉链",
                    "calculation_size": "长25CM",
                    "piece_part": "5#树脂拉头",
                    "piece_quantity": "数量3",
                    "quantity": "数量3",
                    "source": "excel",
                },
                {
                    "type": "配件/辅料",
                    "standard_name_code": "5#树脂拉链",
                    "calculation_size": "长25CM",
                    "piece_part": "#尼龙拉头",
                    "piece_quantity": "数量1",
                    "quantity": "数量1",
                    "source": "excel",
                },
            ]
        }

        display_rows = build_material_display_rows(quote)

        self.assertEqual(display_rows[0]["quantity_display"], "1条、4个")
        self.assertNotIn("缺少片数", display_rows[0]["quantity_display"])


if __name__ == "__main__":
    unittest.main()
