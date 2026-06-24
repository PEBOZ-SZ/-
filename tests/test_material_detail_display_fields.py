from __future__ import annotations

import unittest

from material_piece_summary import build_material_display_rows, build_material_piece_summaries


class MaterialDetailDisplayFieldsTest(unittest.TestCase):
    def test_pending_area_piece_keeps_formula_and_parsed_dimensions(self) -> None:
        quote = {
            "bom_requirement_view": {
                "materials_detail_rows": [
                    {
                        "type": "物料1",
                        "standard_name_code": "FJ-150D记忆布",
                        "calculation_size": "45×25×23CM",
                        "remark": "包身主体",
                        "source": "excel",
                    }
                ]
            }
        }

        summaries = build_material_piece_summaries(quote)

        self.assertEqual(len(summaries), 1)
        piece = summaries[0]["pieces"][0]
        self.assertEqual(piece["status"], "pending")
        self.assertNotIn("待补充", piece["formula"])
        self.assertIn("×", piece["formula"])
        self.assertIn("45×25×23CM", piece["size_text"])
        self.assertIn("缺少", piece["note"])

    def test_groups_same_material_multi_parts_for_display(self) -> None:
        quote = {
            "bom_requirement_view": {
                "materials_detail_rows": [
                    {
                        "type": "物料1",
                        "standard_name_code": "FJ-150D记忆布",
                        "calculation_size": "45×25×23CM",
                        "remark": "包身主体",
                        "usage": "0.2码",
                        "source": "excel",
                    },
                    {
                        "type": "物料2",
                        "standard_name_code": "FJ-150D记忆布",
                        "calculation_size": "45×25×23CM",
                        "remark": "前幅",
                        "usage": "0.25码",
                        "source": "excel",
                    },
                    {
                        "type": "物料3",
                        "standard_name_code": "K080网",
                        "calculation_size": "10×10CM",
                        "remark": "网袋裁片",
                        "usage": "1片",
                        "source": "excel",
                    },
                ]
            }
        }

        display_rows = build_material_display_rows(quote)

        fj_rows = [r for r in display_rows if r["standard_name_code"] == "FJ-150D记忆布"]
        self.assertEqual(len(fj_rows), 1)
        fj = fj_rows[0]
        self.assertEqual(fj["material_name"], "FJ-150D记忆布")
        self.assertEqual(fj["name"], "FJ-150D记忆布")
        self.assertEqual(fj["calculation_size"], "45×25×23CM")
        self.assertEqual(fj["total_usage"], "0.45码")
        self.assertEqual(fj["quantity"], "缺少片数，待复核")
        self.assertEqual(fj["quantity_display"], "缺少片数，待复核")
        self.assertIn("包身主体", fj["parts_text"])
        self.assertIn("前幅", fj["parts_text"])
        self.assertGreaterEqual(len(fj["material_piece_summary"]["pieces"]), 2)
        self.assertTrue(fj["material_piece_summary"]["pending_parts"])

    def test_display_quantity_does_not_fallback_to_usage_when_piece_count_unknown(self) -> None:
        quote = {
            "bom_requirement_view": {
                "materials_detail_rows": [
                    {
                        "type": "物料1",
                        "standard_name_code": "FJ-150D记忆布",
                        "calculation_size": "45*25*23CM",
                        "remark": "包身主体",
                        "usage": "4.95码",
                        "source": "excel",
                    }
                ]
            }
        }

        display_rows = build_material_display_rows(quote)

        self.assertEqual(display_rows[0]["total_usage"], "4.95码")
        self.assertNotEqual(display_rows[0]["quantity"], "4.95码")
        self.assertEqual(display_rows[0]["quantity_display"], "缺少片数，待复核")

    def test_complete_piece_has_quantity_and_subtotal_display(self) -> None:
        quote = {
            "bom_requirement_view": {
                "materials_detail_rows": [
                    {
                        "type": "物料1",
                        "standard_name_code": "FJ-150D记忆布",
                        "calculation_size": "45*25*23CM",
                        "remark": "前片",
                        "usage": "4.95码",
                        "source": "excel",
                    }
                ]
            },
            "material_piece_summaries": [
                {
                    "material_id": "material_1",
                    "material_name": "FJ-150D记忆布",
                    "material_type": "物料1",
                    "calc_size_text": "45*25*23CM",
                    "source": "excel",
                    "covered_parts": ["前片"],
                    "pending_parts": [],
                    "review_hints": [],
                    "is_measurable": True,
                    "is_area_measurable": True,
                    "pieces": [
                        {
                            "piece": "前片",
                            "formula_key": "panel",
                            "formula_text": "长×宽×片数",
                            "size_text": "45×25×2cm",
                            "qty": 2,
                            "unit_area_cm2": 1125,
                            "total_area_cm2": 2250,
                            "source": "remark",
                            "status": "ok",
                            "status_label": "已识别",
                            "note": "",
                        }
                    ],
                    "total_area_cm2": 2250,
                    "total_area_m2": 0.225,
                }
            ],
        }

        display_rows = build_material_display_rows(quote)
        piece = display_rows[0]["material_piece_summary"]["pieces"][0]

        self.assertEqual(piece["quantity_display"], "2")
        self.assertEqual(piece["subtotal_display"], "0.225m²")
        self.assertEqual(display_rows[0]["quantity_display"], "2")

    def test_piece_with_quantity_but_missing_area_marks_missing_size_not_none(self) -> None:
        quote = {
            "bom_requirement_view": {
                "materials_detail_rows": [
                    {
                        "type": "面料1",
                        "standard_name_code": "FJ-150D记忆布",
                        "calculation_size": "45*25*23CM",
                        "source": "excel",
                    }
                ]
            },
            "material_piece_summaries": [
                {
                    "material_id": "material_1_main_fabric_area",
                    "material_name": "FJ-150D记忆布",
                    "material_type": "面料1",
                    "calc_size_text": "45*25*23CM",
                    "is_area_measurable": True,
                    "pieces": [
                        {
                            "piece": "异形片",
                            "formula_text": "长×宽×片数",
                            "size_text": "缺少尺寸",
                            "qty": 2,
                            "unit_area_cm2": None,
                            "total_area_cm2": None,
                            "status": "ok",
                            "status_label": "已识别",
                            "source": "excel",
                        }
                    ],
                }
            ],
        }

        piece = build_material_display_rows(quote)[0]["material_piece_summary"]["pieces"][0]

        self.assertEqual(piece["quantity_display"], "2")
        self.assertEqual(piece["subtotal_display"], "缺少尺寸")
        self.assertNotEqual(piece["subtotal_display"], "无")

    def test_extracts_piece_counts_and_subtotals_from_remark_size_list(self) -> None:
        quote = {
            "bom_requirement_view": {
                "materials_detail_rows": [
                    {
                        "type": "物料1",
                        "standard_name_code": "FJ-150D记忆布",
                        "calculation_size": "45*25*23CM",
                        "remark": "覆盖1套、45*37CM、底部仓、1个、39*12CM、前幅外贴袋、17*15CM、侧面上部拉链挡片、2、68x45。",
                        "usage": "4.95码",
                        "source": "excel",
                    }
                ]
            }
        }

        display_rows = build_material_display_rows(quote)
        pieces = display_rows[0]["material_piece_summary"]["pieces"]
        by_piece = {piece["piece"]: piece for piece in pieces}

        self.assertEqual(by_piece["底部仓"]["quantity_display"], "1")
        self.assertEqual(by_piece["底部仓"]["subtotal_display"], "0.0468m²")
        self.assertEqual(by_piece["前幅外贴袋"]["quantity_display"], "1")
        self.assertEqual(by_piece["前幅外贴袋"]["subtotal_display"], "0.0255m²")
        self.assertEqual(by_piece["侧面上部拉链挡片"]["quantity_display"], "2")
        self.assertEqual(by_piece["侧面上部拉链挡片"]["subtotal_display"], "0.612m²")
        self.assertEqual(display_rows[0]["quantity_display"], "4")

    def test_grouped_rows_pair_adjacent_piece_size_and_quantity(self) -> None:
        rows = [
            {"type": "面料1", "standard_name_code": "FJ-150D记忆布", "calculation_size": "45*25*23CM", "piece_part": "1套", "remark": "包身主片"},
            {"type": "面料1", "standard_name_code": "FJ-150D记忆布", "calculation_size": "45*25*23CM", "piece_part": "45*37CM", "quantity": "数量2片"},
            {"type": "面料1", "standard_name_code": "FJ-150D记忆布", "calculation_size": "45*25*23CM", "piece_part": "底部仓"},
            {"type": "面料1", "standard_name_code": "FJ-150D记忆布", "calculation_size": "45*25*23CM", "piece_part": "1个", "remark": "后幅拉杆套 / 贴片"},
            {"type": "面料1", "standard_name_code": "FJ-150D记忆布", "calculation_size": "45*25*23CM", "piece_part": "39*12CM", "quantity": "数量1片"},
            {"type": "面料1", "standard_name_code": "FJ-150D记忆布", "calculation_size": "45*25*23CM", "piece_part": "前幅外贴袋"},
            {"type": "面料1", "standard_name_code": "FJ-150D记忆布", "calculation_size": "45*25*23CM", "piece_part": "1个", "remark": "左右侧外贴袋"},
            {"type": "面料1", "standard_name_code": "FJ-150D记忆布", "calculation_size": "45*25*23CM", "piece_part": "17*15CM"},
            {"type": "面料1", "standard_name_code": "FJ-150D记忆布", "calculation_size": "45*25*23CM", "piece_part": "侧面上部拉链挡片"},
            {"type": "面料1", "standard_name_code": "FJ-150D记忆布", "calculation_size": "45*25*23CM", "piece_part": "2", "remark": "手提"},
            {"type": "面料1", "standard_name_code": "FJ-150D记忆布", "calculation_size": "45*25*23CM", "piece_part": "68x45"},
        ]
        quote = {"bom_requirement_view": {"materials_detail_rows": rows}}

        display_rows = build_material_display_rows(quote)
        pieces = display_rows[0]["material_piece_summary"]["pieces"]
        by_piece = {piece["piece"]: piece for piece in pieces}

        self.assertEqual(by_piece["包身主片"]["quantity_display"], "2")
        self.assertEqual(by_piece["包身主片"]["subtotal_display"], "0.333m²")
        self.assertEqual(by_piece["后幅拉杆套 / 贴片"]["quantity_display"], "1")
        self.assertEqual(by_piece["后幅拉杆套 / 贴片"]["subtotal_display"], "0.0468m²")
        self.assertEqual(by_piece["左右侧外贴袋"]["quantity_display"], "1")
        self.assertEqual(by_piece["左右侧外贴袋"]["subtotal_display"], "0.0255m²")
        self.assertEqual(by_piece["手提"]["quantity_display"], "2")
        self.assertEqual(by_piece["手提"]["subtotal_display"], "0.612m²")
        self.assertEqual(display_rows[0]["quantity_display"], "6")

    def test_grouped_display_lists_actual_sizes_instead_of_multi_size(self) -> None:
        quote = {
            "bom_requirement_view": {
                "materials_detail_rows": [
                    {
                        "type": "辅料",
                        "standard_name_code": "5#树脂拉链",
                        "calculation_size": "25CM",
                        "remark": "拉链1",
                        "source": "excel",
                    },
                    {
                        "type": "辅料",
                        "standard_name_code": "5#树脂拉链",
                        "calculation_size": "30CM",
                        "remark": "拉链2",
                        "source": "excel",
                    },
                ]
            }
        }

        display_rows = build_material_display_rows(quote)

        self.assertEqual(len(display_rows), 1)
        self.assertNotEqual(display_rows[0]["calculation_size"], "多尺寸")
        self.assertIn("25CM", display_rows[0]["calculation_size"])
        self.assertIn("30CM", display_rows[0]["calculation_size"])


    def test_grouped_display_rows_inherit_pricing_from_quote_items(self) -> None:
        quote = {
            "items": [
                {
                    "name": "FJ-150D记忆布",
                    "spec": "45*25*23CM",
                    "usage": "0.45码",
                    "unit_price": "7.8元/码",
                    "amount": 3.5,
                }
            ],
            "bom_requirement_view": {
                "materials_detail_rows": [
                    {
                        "type": "面料1",
                        "standard_name_code": "FJ-150D记忆布",
                        "calculation_size": "45*25*23CM",
                        "piece_part": "包身主片",
                        "source": "excel",
                    },
                    {
                        "type": "面料2",
                        "standard_name_code": "FJ-150D记忆布",
                        "calculation_size": "45*25*23CM",
                        "piece_part": "前幅外贴袋",
                        "source": "excel",
                    },
                ]
            },
        }

        display_rows = build_material_display_rows(quote)

        self.assertEqual(len(display_rows), 1)
        self.assertEqual(display_rows[0]["unit_price"], "7.8元/码")
        self.assertEqual(display_rows[0]["usage"], "0.45码")
        self.assertEqual(display_rows[0]["amount"], 3.5)


if __name__ == "__main__":
    unittest.main()
