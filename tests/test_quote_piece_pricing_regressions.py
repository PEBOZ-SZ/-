from __future__ import annotations

import unittest

from material_piece_summary import build_material_display_rows
from quote_validation_gate import apply_pricing_gate


class QuotePiecePricingRegressionTest(unittest.TestCase):
    def test_duplicate_bottom_pu_piece_is_merged_and_area_is_calculated(self) -> None:
        quote = {
            "bom_requirement_view": {
                "materials_detail_rows": [
                    {
                        "type": "PU片加强片",
                        "standard_name_code": "PU料",
                        "calculation_size": "45*25*10CM",
                        "piece_part": "底部 PU 片",
                        "remark": "底部 PU 片，45*25CM，覆盖1片。",
                        "source": "remark",
                    },
                    {
                        "type": "PU片加强片",
                        "standard_name_code": "PU料",
                        "calculation_size": "45*25*10CM",
                        "piece_part": "底部 PU 片",
                        "remark": "底部 PU 片，45*25CM，覆盖1片。",
                        "source": "AI补全",
                    },
                    {
                        "type": "PU片加强片",
                        "standard_name_code": "PU料",
                        "calculation_size": "45*25*10CM",
                        "piece_part": "底部 PU 片",
                        "remark": "底部 PU 片，45*25CM，覆盖1片。",
                        "source": "结构推理",
                    },
                ]
            }
        }

        display_rows = build_material_display_rows(quote)
        pieces = display_rows[0]["material_piece_summary"]["pieces"]
        bottom_pieces = [p for p in pieces if p["piece"] == "底部 PU 片"]

        self.assertEqual(len(bottom_pieces), 1)
        self.assertEqual(bottom_pieces[0]["quantity_display"], "1")
        self.assertEqual(bottom_pieces[0]["subtotal_display"], "0.1125m²")
        self.assertAlmostEqual(bottom_pieces[0]["total_area_m2"], 0.1125)

    def test_missing_piece_count_is_review_state_not_plain_none(self) -> None:
        quote = {
            "bom_requirement_view": {
                "materials_detail_rows": [
                    {
                        "type": "PU片加强片",
                        "standard_name_code": "PU料",
                        "calculation_size": "45*25*10CM",
                        "piece_part": "底部 PU 片",
                        "remark": "底部 PU 片，尺寸待补。",
                        "source": "remark",
                    }
                ]
            }
        }

        display_rows = build_material_display_rows(quote)
        piece = display_rows[0]["material_piece_summary"]["pieces"][0]

        self.assertEqual(piece["status"], "pending")
        self.assertEqual(piece["quantity_display"], "缺少片数")
        self.assertIn("缺少片数", piece["subtotal_display"])
        self.assertIn("缺少片数", piece["note"])

    def test_piece_count_can_be_inferred_from_single_table_piece(self) -> None:
        quote = {
            "bom_requirement_view": {
                "materials_detail_rows": [
                    {
                        "type": "PU片加强片",
                        "standard_name_code": "PU料",
                        "calculation_size": "45*25*10CM",
                        "piece_part": "底部 PU 片",
                        "remark": "底部 PU 片，45*25CM。",
                        "source": "remark",
                    }
                ]
            }
        }

        display_rows = build_material_display_rows(quote)
        piece = display_rows[0]["material_piece_summary"]["pieces"][0]

        self.assertEqual(piece["piece"], "底部 PU 片")
        self.assertEqual(piece["quantity_display"], "1")
        self.assertEqual(piece["subtotal_display"], "0.1125m²")
        self.assertIn(piece["status"], {"inferred", "ok"})

    def test_calculated_bottom_pu_piece_keeps_human_formula_and_size(self) -> None:
        quote = {
            "bom_requirement_view": {
                "materials_detail_rows": [
                    {
                        "type": "PU片加强片",
                        "standard_name_code": "PU料",
                        "calculation_size": "45*25*10CM",
                        "piece_part": "底部 PU 片",
                        "remark": "底部 PU 片，45*25CM。",
                        "source": "remark",
                    }
                ]
            }
        }

        piece = build_material_display_rows(quote)[0]["material_piece_summary"]["pieces"][0]

        self.assertEqual(piece["formula"], "长×宽×片数")
        self.assertEqual(piece["formula_text"], "长×宽×片数")
        self.assertIn("45", piece["size_text"])
        self.assertIn("25", piece["size_text"])
        self.assertNotIn(piece["formula"], {"", "-", "—", "pair_size"})
        self.assertNotIn(piece["size_text"], {"", "-", "—"})
        self.assertEqual(piece["subtotal_display"], "0.1125m²")

    def test_main_material_quantity_summarizes_inferred_piece_counts(self) -> None:
        quote = {
            "bom_requirement_view": {
                "materials_detail_rows": [
                    {
                        "type": "面料1",
                        "standard_name_code": "FJ-150D记忆布",
                        "calculation_size": "45*25*23CM",
                        "piece_part": "前片",
                        "source": "结构推断",
                    },
                    {
                        "type": "面料1",
                        "standard_name_code": "FJ-150D记忆布",
                        "calculation_size": "45*25*23CM",
                        "piece_part": "后片",
                        "source": "结构推断",
                    },
                    {
                        "type": "面料1",
                        "standard_name_code": "FJ-150D记忆布",
                        "calculation_size": "45*25*23CM",
                        "piece_part": "左右侧片",
                        "source": "结构推断",
                    },
                    {
                        "type": "面料1",
                        "standard_name_code": "FJ-150D记忆布",
                        "calculation_size": "45*25*23CM",
                        "piece_part": "底片",
                        "source": "结构推断",
                    },
                ]
            }
        }

        row = build_material_display_rows(quote)[0]
        pieces = row["material_piece_summary"]["pieces"]

        self.assertEqual(row["material_name"], "FJ-150D记忆布")
        self.assertEqual(row["quantity_display"], "5")
        self.assertNotEqual(row["quantity_display"], "无")
        self.assertTrue(all(piece["quantity_display"] not in {"", "-", "无"} for piece in pieces))
        self.assertTrue(all(piece["subtotal_display"] not in {"", "-", "无"} for piece in pieces))
        self.assertTrue(any(piece["status_label"] == "推断待核" for piece in pieces))

    def test_main_quantity_reports_known_pieces_and_pending_parts(self) -> None:
        quote = {
            "bom_requirement_view": {
                "materials_detail_rows": [
                    {
                        "type": "面料1",
                        "standard_name_code": "FJ-150D记忆布",
                        "calculation_size": "45*25*23CM",
                        "piece_part": "前片",
                        "source": "结构推断",
                    },
                    {
                        "type": "面料1",
                        "standard_name_code": "FJ-150D记忆布",
                        "calculation_size": "45*25*23CM",
                        "piece_part": "特殊异形片",
                        "remark": "特殊异形片，尺寸和片数待补",
                        "source": "remark",
                    },
                ]
            }
        }

        row = build_material_display_rows(quote)[0]

        self.assertEqual(row["quantity_display"], "已识别1片，1项待核")
        self.assertNotEqual(row["quantity_display"], "无")

    def test_included_quote_row_without_unit_price_is_blocked(self) -> None:
        result = {
            "detail_rows": [
                {
                    "name": "PU料",
                    "usage": "0.1125m²",
                    "unit_price": "",
                    "amount": 0,
                    "included_in_quote": True,
                }
            ]
        }

        apply_pricing_gate(result, {"items": result["detail_rows"]}, manual_confirmed=False)

        row = result["detail_rows"][0]
        self.assertEqual(row["validation_status"], "HIGH_RISK")
        self.assertIn("core_unit_price_missing", row["risk_flags"])
        self.assertEqual(row["unit_price"], "待补价")
        self.assertIn("未匹配单价", row["validation_detail"])
        self.assertFalse(result["pricing_gate"]["final_price_allowed"])


if __name__ == "__main__":
    unittest.main()
