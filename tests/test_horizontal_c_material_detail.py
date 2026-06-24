import base64
import unittest
from pathlib import Path

from admin_bom_requirement_view import (
    enrich_requirement_fields_from_material_details,
    extract_material_detail_rows_from_rows,
    extract_requirement_fields_from_rows,
)
from demand_parser import is_demand_template, parse_demand_from_payload, parse_demand_from_rows
from sheet_parser import parse_sheet_items_from_payload

REAL_XLSX = Path(r"D:/正确版/表格_材料布局清爽版_补全手提网布.xlsx")
if not REAL_XLSX.exists():
    REAL_XLSX = Path(r"D:/正确数/表格_材料布局清爽版_补全手提网布.xlsx")
if not REAL_XLSX.exists():
    REAL_XLSX = next(Path(__file__).resolve().parents[2].rglob("*补全手提网布*.xlsx"), None)

FALSE_GROUP_ITEM_NAMES = (
    "类型",
    "面料1",
    "PU料/加强片",
    "内部拖料/无纺布",
    "配件/辅料",
)

HORIZONTAL_C_ROWS = [
    ["C. 材料与配件（标准名/编码）"],
    [
        "类型",
        "主材料/规格",
        "对应核算尺寸",
        "部位/裁片1",
        "尺寸/数量/备注1",
        "部位/裁片2",
        "尺寸/数量/备注2",
        "部位/裁片3",
        "尺寸/数量/备注3",
    ],
    [
        "面料1",
        "FJ-150D记忆布",
        "45*25*23CM",
        "包身主片",
        "45*37CM；底宽/侧宽25CM",
        "底部独立仓",
        "高10CM",
        "手提",
        "68x45",
    ],
    [
        "里布/内衬",
        "色丁布",
        "45*25*38CM",
        "主里布",
        "45*25*38CM",
    ],
    [
        "配件/辅料",
        "多规格配件",
        "",
        "拉链1",
        "5#树脂拉链；长25CM；数量1条；按条计价",
        "拉头1",
        "5#树脂拉头；数量3个；按个计价",
    ],
]

B_SECTION_ROWS = [
    ["B. 产品规格"],
    ["产品类型", "产品名称/款号", "L(cm)", "W(cm)", "H(cm)", "结构复杂度"],
    ["收纳包", "手提收纳包", "45", "25", "38", "标准"],
]


def _payload_from_xlsx(path: Path) -> dict:
    return {
        "name": path.name,
        "content_base64": base64.b64encode(path.read_bytes()).decode(),
    }


class HorizontalCMaterialDetailTest(unittest.TestCase):
    def test_expand_fabric_row_into_multiple_details(self) -> None:
        details = extract_material_detail_rows_from_rows(HORIZONTAL_C_ROWS)
        fabric_rows = [r for r in details if r.get("type") == "面料1"]
        self.assertGreaterEqual(len(fabric_rows), 3)
        first = fabric_rows[0]
        self.assertEqual(first["standard_name_code"], "FJ-150D记忆布")
        self.assertEqual(first["piece_part"], "包身主片")
        self.assertEqual(first["piece_size"], "45*37CM")
        self.assertEqual(first["piece_quantity"], "无")
        self.assertIn("底宽", first["remark"])
        self.assertNotIn("45*37CM", first["remark"])
        self.assertEqual(first["pricing_section"], "C")
        self.assertEqual(first["included_in_quote"], "是")
        self.assertFalse(any(r["standard_name_code"] == "包身主片" for r in details))

        zipper = next(r for r in details if r.get("piece_part") == "拉链1")
        self.assertEqual(zipper["standard_name_code"], "5#树脂拉链")
        self.assertEqual(zipper["piece_size"], "长25CM")
        self.assertEqual(zipper["piece_quantity"], "数量1条")
        self.assertIn("按条计价", zipper["remark"])
        self.assertNotIn("多规格配件", zipper["standard_name_code"])

    def test_legacy_c_fields_filled_from_horizontal_details(self) -> None:
        details = extract_material_detail_rows_from_rows(HORIZONTAL_C_ROWS)
        req = enrich_requirement_fields_from_material_details(
            extract_requirement_fields_from_rows(B_SECTION_ROWS + HORIZONTAL_C_ROWS),
            details,
        )
        self.assertIn("FJ-150D记忆布", req.get("外料(标准名/编码)", ""))
        self.assertIn("色丁布", req.get("里料(标准名/编码)", ""))
        self.assertIn("5#树脂拉链", req.get("拉链", ""))
        self.assertIn("5#树脂拉头", req.get("拉头类型", ""))

    def test_product_fields_from_section_b_not_filename(self) -> None:
        rows = B_SECTION_ROWS + HORIZONTAL_C_ROWS
        self.assertTrue(is_demand_template(rows))
        parsed = parse_demand_from_rows(
            rows,
            file_name="表格_材料布局清爽版_补全手提网布.xlsx",
            sheet_name="需求表(填写区)",
        )
        self.assertEqual(parsed.product_name, "手提收纳包")
        self.assertEqual(parsed.product_type, "收纳包")
        self.assertEqual(parsed.product_size.get("LCM"), 45.0)
        self.assertGreater(len(parsed.materials_detail_rows), 5)
        self.assertGreater(len(parsed.materials), 5)
        self.assertNotIn(parsed.file_name, parsed.product_name)

    @unittest.skipUnless(REAL_XLSX and REAL_XLSX.exists(), "real acceptance xlsx not found")
    def test_real_xlsx_demand_and_sheet_parse(self) -> None:
        payload = _payload_from_xlsx(REAL_XLSX)
        demand = parse_demand_from_payload(payload)
        sheet = parse_sheet_items_from_payload(payload)

        self.assertEqual(demand.product_name, "手提收纳包")
        self.assertEqual(demand.product_type, "收纳包")

        details = demand.materials_detail_rows
        self.assertGreaterEqual(len(details), 15)
        self.assertTrue(
            any(
                r.get("piece_part") == "手提" and r.get("piece_size") == "68x45"
                for r in details
            )
        )
        self.assertTrue(
            any(
                r.get("standard_name_code") == "k080网" and r.get("piece_part") == "裁片8"
                for r in details
            )
        )

        item_names = [str(item.get("name") or "") for item in sheet["items"]]
        for false_name in FALSE_GROUP_ITEM_NAMES:
            self.assertNotIn(false_name, item_names, msg=f"false item leaked: {false_name}")

        req = enrich_requirement_fields_from_material_details(
            sheet["requirement_fields"],
            sheet["materials_detail_rows"],
        )
        self.assertIn("FJ-150D记忆布", req["外料(标准名/编码)"])
        self.assertIn("色丁布", req["里料(标准名/编码)"])
        self.assertIn("5#树脂拉链", req["拉链"])
        self.assertIn("3#尼龙拉链", req["拉链"])
        self.assertIn("5#树脂拉头", req["拉头类型"])
        self.assertIn("3#尼龙拉头", req["拉头类型"])

        self.assertTrue(
            any(
                r.get("piece_part") == "底部隔离片"
                and r.get("piece_size") in {"", "无"}
                and "按实际尺寸填写" in str(r.get("remark") or "")
                for r in details
            )
        )
        self.assertTrue(
            any(
                r.get("piece_part") == "珍珠棉垫片"
                and r.get("piece_size") == "45*25*10CM"
                and r.get("piece_quantity") == "数量1片/套"
                for r in details
            )
        )

        item_names = [str(item.get("name") or "") for item in sheet["items"]]
        self.assertNotIn("多规格配件", item_names)
        self.assertIn("5#树脂拉链", item_names)
        self.assertIn("3#尼龙拉链", item_names)
        self.assertIn("5#树脂拉头", item_names)
        self.assertIn("3#尼龙拉头", item_names)
        self.assertLess(len(sheet["items"]), len(sheet["materials_detail_rows"]))


    def test_material_detail_items_group_same_material_across_numbered_types(self) -> None:
        from sheet_parser import material_detail_rows_to_items

        rows = [
            {
                "type": "面料1",
                "standard_name_code": "FJ-150D记忆布",
                "calculation_size": "45*25*23CM",
                "piece_part": "包身主片",
                "remark": "主片",
                "pricing_section": "C",
                "included_in_quote": "是",
            },
            {
                "type": "面料2",
                "standard_name_code": "FJ-150D记忆布",
                "calculation_size": "45*25*23CM",
                "piece_part": "前幅外贴袋",
                "remark": "外贴袋",
                "pricing_section": "C",
                "included_in_quote": "是",
            },
            {
                "type": "PU料/加强片",
                "standard_name_code": "PU料",
                "calculation_size": "45*25*10CM",
                "piece_part": "底部PU片",
                "remark": "底部",
                "pricing_section": "C",
                "included_in_quote": "是",
            },
        ]

        items = material_detail_rows_to_items(rows)

        names = [item["name"] for item in items]
        self.assertEqual(names.count("FJ-150D记忆布"), 1)
        fj = next(item for item in items if item["name"] == "FJ-150D记忆布")
        self.assertIn("包身主片", fj["piece_part"])
        self.assertIn("前幅外贴袋", fj["piece_part"])
        self.assertEqual(fj["section_key"], "C")


if __name__ == "__main__":
    unittest.main()
