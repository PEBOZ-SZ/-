from __future__ import annotations

import unittest

from server import build_structure_confirmation_payload


class StructureConfirmationPayloadTest(unittest.TestCase):
    def test_confirmation_rows_use_grouped_display_rows_with_pricing(self) -> None:
        payload = {
            "items": [
                {
                    "name": "FJ-150D记忆布",
                    "spec": "45*25*23CM",
                    "usage": "0.45码",
                    "unit_price": "7.8元/码",
                    "amount": 3.5,
                }
            ],
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

        response = build_structure_confirmation_payload(
            payload,
            sheet_parse_result={"file_name": "demo.xlsx"},
            structure_text="",
        )

        rows = response["items_confirmation"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "FJ-150D记忆布")
        self.assertEqual(rows[0]["unit_price"], "7.8元/码")
        self.assertEqual(rows[0]["usage"], "0.45码")


    def test_confirmation_rows_merge_duplicate_quote_materials(self) -> None:
        payload = {
            "items": [
                {
                    "name": "FJ-150D memory fabric",
                    "spec": "45*25*2",
                    "usage": "0.45yd",
                    "unit_price": "7.8/yd",
                    "amount": 3.51,
                    "calc_note": "piece area total",
                    "section_key": "C",
                },
                {
                    "name": " FJ-150D memory fabric ",
                    "spec": "45*25*2",
                    "usage": "0.45yd",
                    "unit_price": "7.8/yd",
                    "amount": 3.51,
                    "calc_method": "piece area total",
                    "area": "C",
                },
                {
                    "name": "FJ-150D memory fabric",
                    "spec": "45*25*2",
                    "usage": "0.45yd",
                    "unit_price": "7.8/yd",
                    "amount": 3.51,
                    "calc_note": "piece area total",
                    "section_key": "C",
                },
            ],
        }

        response = build_structure_confirmation_payload(
            payload,
            sheet_parse_result={"file_name": "demo.xlsx"},
            structure_text="",
        )

        rows = response["items_confirmation"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "FJ-150D memory fabric")
        self.assertEqual(rows[0]["usage"], "1.35yd")
        self.assertAlmostEqual(float(rows[0]["amount"]), 10.53)
        self.assertEqual(rows[0]["merged_duplicate_count"], 3)
        self.assertEqual(rows[0]["source_row_indices"], [0, 1, 2])



if __name__ == "__main__":
    unittest.main()
