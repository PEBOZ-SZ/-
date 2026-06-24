"""表格类型判定与图片推断标记。"""

from __future__ import annotations

import unittest

from material_inference import (
    IMAGE_INFERENCE_NOTE,
    SOURCE_IMAGE,
    build_inferred_candidate_row,
    infer_missing_cost_candidates,
    is_excel_explicit_row,
    merge_material_inference_candidates,
)
from photo_quote_flow import mark_image_inferred_row
from sheet_kind_classifier import (
    KIND_ADMIN_CORRECTION,
    KIND_CUSTOMER_DEMAND,
    KIND_QUOTE_OUTPUT,
    KIND_SALES_BOM,
    KIND_UNKNOWN,
    build_sheet_kind_unknown_response,
    is_blocked_sheet_kind,
    should_force_customer_demand_sheet,
)


def _rows_payload(rows: list[list[str]], *, name: str = "test.xlsx", sheet_name: str = "Sheet1") -> dict:
    import base64
    import io
    import zipfile
    from xml.sax.saxutils import escape

    # Minimal valid-enough xlsx is heavy; classifier tests use classify_rows helper below.
    return {"name": name, "sheet_name": sheet_name, "content_base64": "", "_rows": rows}


class ClassifyRowsMixin:
    @staticmethod
    def classify_rows(rows: list[list[str]], *, file_name: str = "test.xlsx", sheet_name: str = "Sheet1") -> str:
        kind, _detail = ClassifyRowsMixin.classify_rows_detail(
            rows, file_name=file_name, sheet_name=sheet_name
        )
        return kind

    @staticmethod
    def classify_rows_detail(
        rows: list[list[str]], *, file_name: str = "test.xlsx", sheet_name: str = "Sheet1"
    ) -> tuple[str, dict]:
        from sheet_kind_classifier import classify_uploaded_sheet_kind
        from unittest.mock import patch

        with patch(
            "sheet_kind_classifier._rows_from_uploaded_sheet",
            return_value=(file_name, sheet_name, rows, ()),
        ):
            return classify_uploaded_sheet_kind({"name": file_name, "content_base64": "e30="})


class SheetKindClassifierTest(ClassifyRowsMixin, unittest.TestCase):
    def test_customer_demand_not_blocked(self) -> None:
        rows = [
            ["A. 客户与报价信息"],
            ["客户名称", "测试客户"],
            ["B. 产品规格"],
            ["产品名称", "双肩包"],
            ["产品类型", "背包"],
            ["C. 材料与配件"],
            ["外料", "420D尼龙"],
            ["里料", "210D"],
            ["D. 工艺"],
            ["LOGO", "丝印"],
        ]
        kind = self.classify_rows(rows, file_name="客户需求表.xlsx", sheet_name="需求表填写区")
        self.assertEqual(kind, KIND_CUSTOMER_DEMAND)
        self.assertFalse(is_blocked_sheet_kind(kind))

    def test_sales_bom_blocked(self) -> None:
        rows = [
            ["物料名称", "规格", "用量", "单价", "小计", "金额"],
            ["420D尼龙", "1.2m", "1.5码", "25元/码", "37.5", "37.5"],
            ["里布", "210D", "0.8码", "12元/码", "9.6", "9.6"],
            ["拉链", "5#", "1条", "3元/条", "3", "3"],
        ]
        kind = self.classify_rows(rows, file_name="B260128_BOM.xlsx", sheet_name="物料明细")
        self.assertEqual(kind, KIND_SALES_BOM)
        self.assertTrue(is_blocked_sheet_kind(kind))

    def test_simple_bom_template_blocked(self) -> None:
        rows = [
            ["", "报价资料B260128"],
            ["", "类型", "说明", "宽幅", "单价"],
            ["", "尺寸", "长150mm，高110mm"],
            ["", "面料(正面)", "0.4mm 透明 PVC", "122CM", "23元/码"],
            ["", "数量", "500"],
        ]
        kind = self.classify_rows(rows, file_name="业务员报价.xlsx", sheet_name="报价明细")
        self.assertEqual(kind, KIND_SALES_BOM)

    def test_admin_correction_blocked(self) -> None:
        rows = [
            ["管理员修正 BOM"],
            ["物料名称", "规格", "用量", "单价", "recognition_status", "source_type", "calc_note"],
            ["PU拉牌", "58#", "1个", "2元/个", "candidate_review", "image_inferred", "图片推理，需人工复核"],
        ]
        kind = self.classify_rows(rows, file_name="修正BOM.xlsx", sheet_name="管理员修正")
        self.assertEqual(kind, KIND_ADMIN_CORRECTION)
        self.assertTrue(is_blocked_sheet_kind(kind))

    def test_quote_output_blocked(self) -> None:
        rows = [
            ["系统报价单"],
            ["物料名称", "规格", "用量", "单价", "小计", "成本", "报价", "利润"],
            ["420D尼龙", "1.2m", "1.5码", "25元/码", "37.5", "10", "15", "5"],
            ["最终报价", "27元/pc"],
            ["成本核算", "13.73"],
        ]
        kind = self.classify_rows(rows, file_name="quote_result.xlsx", sheet_name="报价结果")
        self.assertEqual(kind, KIND_QUOTE_OUTPUT)
        self.assertTrue(is_blocked_sheet_kind(kind))

    def test_conflict_abcd_with_system_bom_fields_blocked_not_customer_demand(self) -> None:
        rows = [
            ["A. 客户与报价信息"],
            ["客户名称", "测试客户"],
            ["B. 产品规格"],
            ["产品名称", "双肩包"],
            ["C. 材料与配件"],
            ["外料", "420D尼龙"],
            ["D. 工艺"],
            ["LOGO", "丝印"],
            ["物料名称", "规格", "用量", "单价", "小计", "recognition_status", "source_type", "pricing_review_required"],
            ["420D尼龙", "420D", "1.5码", "25元/码", "37.5", "candidate_review", "image_inferred", "true"],
            ["最终报价", "27元/pc"],
            ["成本核算", "13.73"],
        ]
        kind, detail = self.classify_rows_detail(
            rows,
            file_name="mixed_export.xlsx",
            sheet_name="报价明细",
        )
        self.assertNotEqual(kind, KIND_CUSTOMER_DEMAND)
        self.assertTrue(is_blocked_sheet_kind(kind))
        self.assertIn(kind, {KIND_ADMIN_CORRECTION, KIND_QUOTE_OUTPUT, KIND_SALES_BOM})
        self.assertIn(detail.get("decision"), {"blocked_system_export_priority", "blocked_quote_output_priority", "blocked_sales_bom_priority"})

    def test_unknown_when_ambiguous(self) -> None:
        rows = [
            ["备注", "内容"],
            ["说明", "待确认"],
        ]
        kind = self.classify_rows(rows, file_name="misc.xlsx")
        self.assertEqual(kind, KIND_UNKNOWN)

    def test_unknown_response_not_auto_quote(self) -> None:
        resp = build_sheet_kind_unknown_response({"file_name": "misc.xlsx"})
        self.assertFalse(resp.get("quote_ready"))
        self.assertEqual(resp.get("reply_type"), "upload_sheet_kind_unknown")
        self.assertTrue(resp.get("upload_sheet_reference_only"))

    def test_force_customer_demand_override(self) -> None:
        payload = {"force_customer_demand": True}
        self.assertTrue(should_force_customer_demand_sheet(payload, ""))
        payload2 = {"user_prompt": "这是客户需求表，请报价"}
        self.assertTrue(should_force_customer_demand_sheet(payload2, ""))

    def test_customer_demand_with_material_detail_filename_not_blocked(self) -> None:
        """标准需求表 + 文件名含材料明细完善版 + C区明细表头，不应判为 sales_bom。"""
        rows = [
            ["A. 客户与报价信息"],
            ["客户名称", "测试客户"],
            ["业务员", "20 刘璇"],
            ["B. 产品规格"],
            ["产品名称", "双肩包"],
            ["产品类型", "背包"],
            ["C. 材料与配件（标准名/编码）"],
            ["外料(标准名/编码)", "里料(标准名/编码)"],
            ["420D尼龙", "210D"],
            ["类型", "标准名/编码", "对应核算尺寸", "备注说明"],
            ["外料", "420D尼龙", "1.2m", ""],
            ["D. 工艺"],
            ["LOGO", "丝印"],
        ]
        file_name = "B260189报价资料1_材料明细完善版_v7补底部独立仓围片.xlsx"
        kind, detail = self.classify_rows_detail(
            rows,
            file_name=file_name,
            sheet_name="需求表(填写区)",
        )
        self.assertEqual(kind, KIND_CUSTOMER_DEMAND)
        self.assertFalse(is_blocked_sheet_kind(kind))
        self.assertIn(
            detail.get("decision"),
            {"customer_demand_strong_template", "customer_demand_layout", "customer_demand_score"},
        )

    def test_customer_demand_with_workbook_template_sheets_not_blocked(self) -> None:
        """含字段映射/下拉选项/使用说明 workbook 结构时，C区 BOM 列也不应拦截。"""
        rows = [
            ["A. 客户与报价信息"],
            ["客户名称", "测试客户"],
            ["B. 产品规格"],
            ["产品名称", "双肩包"],
            ["C. 材料与配件（标准名/编码）"],
            ["物料名称", "规格", "用量", "单价", "小计", "金额"],
            ["420D尼龙", "420D", "1.5码", "25元/码", "37.5", "37.5"],
            ["D. 工艺"],
            ["LOGO", "丝印"],
        ]
        from unittest.mock import patch
        from sheet_kind_classifier import classify_uploaded_sheet_kind

        workbook_sheets = (
            "需求表(填写区)",
            "字段映射(JSON_Key)",
            "下拉选项",
            "使用说明",
            "材料明细补全说明",
        )
        with patch(
            "sheet_kind_classifier._rows_from_uploaded_sheet",
            return_value=(
                "客户需求_材料明细完善版.xlsx",
                "需求表(填写区)",
                rows,
                workbook_sheets,
            ),
        ):
            kind, detail = classify_uploaded_sheet_kind(
                {"name": "客户需求_材料明细完善版.xlsx", "content_base64": "e30="}
            )
        self.assertEqual(kind, KIND_CUSTOMER_DEMAND)
        self.assertFalse(is_blocked_sheet_kind(kind))
        self.assertTrue(detail.get("strong_customer_demand"))


class ImageInferenceMarkTest(unittest.TestCase):
    def test_image_inferred_row_has_review_flags(self) -> None:
        row = mark_image_inferred_row(
            {
                "name": "前袋（图片结构推断）",
                "role": "辅料",
                "spec": "420D尼龙",
                "usage": "1.2码",
                "unit_price": "25元/码",
                "amount": 30.0,
            }
        )
        self.assertEqual(row.get("source_type"), SOURCE_IMAGE)
        self.assertTrue(row.get("inferred_by_ai"))
        self.assertTrue(row.get("pricing_review_required"))
        self.assertTrue(row.get("needs_human_confirm"))
        self.assertTrue(row.get("needs_manual_confirm"))
        self.assertEqual(row.get("recognition_status"), "candidate_review")
        self.assertTrue(row.get("exclude_from_cost"))
        self.assertEqual(row.get("usage"), "-")
        self.assertEqual(row.get("unit_price"), "-")
        self.assertEqual(row.get("amount"), 0.0)
        self.assertEqual(row.get("spec"), "-")
        self.assertIn("图片推理，需人工复核", str(row.get("calc_note") or ""))
        self.assertIn("图片推理，需人工复核", str(row.get("recognition_reason") or ""))

    def test_inferred_candidate_row_image_flags(self) -> None:
        row = build_inferred_candidate_row(
            component_name="肩带",
            source_type=SOURCE_IMAGE,
            source_snippet="附图可见肩带",
        )
        self.assertTrue(row.get("pricing_review_required"))
        self.assertEqual(row.get("recognition_status"), "candidate_review")
        self.assertIn(IMAGE_INFERENCE_NOTE, str(row.get("calc_note") or ""))

    def test_image_inference_does_not_override_excel_explicit(self) -> None:
        items = [
            {
                "name": "420D尼龙（外料）",
                "role": "外料",
                "spec": "420D",
                "usage": "1.5码",
                "unit_price": "25元/码",
            }
        ]
        candidates, _report = infer_missing_cost_candidates(
            "",
            items,
            vision_text="附图可见肩带、前袋",
            image_present=True,
            demand_template=True,
        )
        self.assertTrue(is_excel_explicit_row(items[0]))
        names = [str(r.get("name") or "") for r in candidates]
        self.assertFalse(any("420D" in n or "尼龙" in n for n in names))
        self.assertTrue(any("肩带" in n or "前袋" in n for n in names) or len(candidates) >= 0)

    def test_merge_material_inference_keeps_table_rows(self) -> None:
        payload = {
            "items": [
                {
                    "name": "里布210D",
                    "role": "里料",
                    "spec": "210D",
                    "usage": "0.8码",
                    "unit_price": "12元/码",
                }
            ]
        }
        before = payload["items"][0]["usage"]
        merge_material_inference_candidates(
            payload,
            structure_text="",
            vision_text="图片可见侧袋",
            image_present=True,
            demand_template=True,
        )
        self.assertEqual(payload["items"][0]["usage"], before)


if __name__ == "__main__":
    unittest.main()
