from __future__ import annotations

import unittest

from admin_bom_requirement_view import extract_material_detail_rows_from_rows
from material_piece_summary import build_material_display_rows


class HorizontalCThreeColumnLayoutTest(unittest.TestCase):
    def test_expand_part_size_quantity_triplets(self) -> None:
        rows = [
            ["C. 材料与配件（标准名/编码）"],
            [
                "类型",
                "主材料/规格",
                "对应核算尺寸",
                "数量",
                "部位/裁片1",
                "尺寸1",
                "数量1",
                "部位/裁片2",
                "尺寸2",
                "数量2",
            ],
            [
                "内部拖料/无纺布",
                "100G无纺布",
                "45*25*38CM",
                "1",
                "1200G丝绵",
                "45*25*38CM",
                "1",
                "",
                "",
                "",
            ],
        ]

        details = extract_material_detail_rows_from_rows(rows)

        self.assertEqual(len(details), 1)
        self.assertEqual(details[0]["standard_name_code"], "100G无纺布")
        self.assertEqual(details[0]["piece_part"], "1200G丝绵")
        self.assertEqual(details[0]["piece_size"], "45*25*38CM")
        self.assertEqual(details[0]["piece_quantity"], "数量1")

    def test_display_rows_use_explicit_triplet_piece_quantity(self) -> None:
        quote = {
            "bom_requirement_view": {
                "materials_detail_rows": [
                    {
                        "type": "material",
                        "standard_name_code": "100G nonwoven",
                        "calculation_size": "45*25*38CM",
                        "piece_part": "padding",
                        "piece_size": "45*25*38CM",
                        "piece_quantity": "数量1",
                        "source": "excel",
                    }
                ]
            }
        }

        display_rows = build_material_display_rows(quote)
        piece = display_rows[0]["material_piece_summary"]["pieces"][0]

        self.assertEqual(display_rows[0]["quantity_display"], "1")
        self.assertEqual(piece["piece"], "padding")
        self.assertEqual(piece["quantity_display"], "1")
        self.assertNotIn("缺少片数", piece["subtotal_display"])

    def test_material_name_with_gram_weight_is_not_treated_as_piece_count(self) -> None:
        quote = {
            "bom_requirement_view": {
                "materials_detail_rows": [
                    {
                        "type": "padding",
                        "standard_name_code": "100G nonwoven",
                        "calculation_size": "45*25*38CM",
                        "piece_part": "1200G cotton",
                        "piece_size": "45*25*38CM",
                        "piece_quantity": "1",
                        "source": "excel",
                    }
                ]
            }
        }

        display_rows = build_material_display_rows(quote)
        piece = display_rows[0]["material_piece_summary"]["pieces"][0]

        self.assertEqual(display_rows[0]["quantity_display"], "1")
        self.assertEqual(piece["piece"], "1200G cotton")
        self.assertEqual(piece["quantity_display"], "1")

    def test_single_row_quantity_and_calc_size_fallback_to_inferred_piece(self) -> None:
        quote = {
            "bom_requirement_view": {
                "materials_detail_rows": [
                    {
                        "type": "mesh",
                        "standard_name_code": "k080 mesh",
                        "calculation_size": "10*10CM",
                        "quantity": "1",
                        "source": "excel",
                    }
                ]
            }
        }

        display_rows = build_material_display_rows(quote)
        piece = display_rows[0]["material_piece_summary"]["pieces"][0]

        self.assertEqual(display_rows[0]["quantity_display"], "1")
        self.assertEqual(piece["quantity_display"], "1")
        self.assertNotIn("缺少片数", piece["subtotal_display"])


if __name__ == "__main__":
    unittest.main()
