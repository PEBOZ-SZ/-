from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class QuoteDraftPatchTests(unittest.TestCase):
    def test_parse_quantity_margin_processing_fee_and_material_price(self) -> None:
        from quote_draft_patch import parse_quote_draft_patches

        result = parse_quote_draft_patches("PU料按6.5，数量改300，毛利改30%，加工费改15")

        self.assertEqual(result["intent"], "patch_draft")
        self.assertTrue(result["needs_recalculate"])
        self.assertIn({"op": "set_quantities", "quantities": [300]}, result["patches"])
        self.assertIn({"op": "set_margin", "gross_margin_rate": 0.30}, result["patches"])
        self.assertIn({"op": "set_processing_fee", "processing_fee": 15}, result["patches"])
        self.assertIn({"op": "set_material_price", "material": "PU料", "unit_price": 6.5}, result["patches"])

    def test_parse_short_quantity(self) -> None:
        from quote_draft_patch import parse_quote_draft_patches

        result = parse_quote_draft_patches("300件")

        self.assertEqual(result["intent"], "patch_draft")
        self.assertEqual(result["patches"], [{"op": "set_quantities", "quantities": [300]}])

    def test_parse_material_usage_and_bom_inclusion(self) -> None:
        from quote_draft_patch import parse_quote_draft_patches

        result = parse_quote_draft_patches("600D牛津布用量按0.56平方，肩带和固定带都加入正式BOM")

        self.assertEqual(result["intent"], "patch_draft")
        self.assertIn(
            {"op": "set_material_usage", "material": "600D牛津布", "usage": 0.56},
            result["patches"],
        )
        self.assertIn(
            {"op": "set_material_included", "material": "肩带", "included": True},
            result["patches"],
        )
        self.assertIn(
            {"op": "set_material_included", "material": "固定带", "included": True},
            result["patches"],
        )

    def test_material_usage_does_not_also_parse_as_price(self) -> None:
        from quote_draft_patch import parse_quote_draft_patches

        result = parse_quote_draft_patches("600D牛津布用量按0.56平方")

        self.assertEqual(
            result["patches"],
            [{"op": "set_material_usage", "material": "600D牛津布", "usage": 0.56}],
        )

    def test_material_price_phrases_parse_as_price(self) -> None:
        from quote_draft_patch import parse_quote_draft_patches

        pu = parse_quote_draft_patches("PU料按6.5")
        box = parse_quote_draft_patches("箱子按5元")

        self.assertEqual(
            pu["patches"],
            [{"op": "set_material_price", "material": "PU料", "unit_price": 6.5}],
        )
        self.assertEqual(
            box["patches"],
            [{"op": "set_material_price", "material": "箱子", "unit_price": 5.0}],
        )

    def test_parse_exclude_and_delete_material(self) -> None:
        from quote_draft_patch import parse_quote_draft_patches

        excluded = parse_quote_draft_patches("箱子不参与报价")
        deleted = parse_quote_draft_patches("删除箱子")

        self.assertIn(
            {"op": "set_material_included", "material": "箱子", "included": False},
            excluded["patches"],
        )
        self.assertIn({"op": "delete_material", "material": "箱子"}, deleted["patches"])

    def test_parse_confirm_save_and_recalculate(self) -> None:
        from quote_draft_patch import parse_quote_draft_patches

        self.assertEqual(parse_quote_draft_patches("确认保存")["intent"], "confirm_save")
        self.assertEqual(parse_quote_draft_patches("保存提交审批")["intent"], "confirm_save")
        self.assertEqual(parse_quote_draft_patches("重新计算")["intent"], "recalculate")

    def test_unknown_text_returns_clarify_without_patches(self) -> None:
        from quote_draft_patch import parse_quote_draft_patches

        result = parse_quote_draft_patches("这个感觉再看看")

        self.assertEqual(result["intent"], "clarify")
        self.assertEqual(result["patches"], [])
        self.assertFalse(result["needs_recalculate"])

    def test_parse_multi_quantity_tiers(self) -> None:
        from quote_draft_patch import parse_quote_draft_patches

        result = parse_quote_draft_patches("数量改成500和1000两档")

        self.assertEqual(result["intent"], "patch_draft")
        self.assertEqual(result["patches"], [{"op": "set_quantities", "quantities": [500, 1000]}])

    def test_parse_margin_points(self) -> None:
        from quote_draft_patch import parse_quote_draft_patches

        result = parse_quote_draft_patches("这次毛利按28个点")

        self.assertEqual(result["intent"], "patch_draft")
        self.assertEqual(result["patches"], [{"op": "set_margin", "gross_margin_rate": 0.28}])

    def test_parse_business_material_phrases(self) -> None:
        from quote_draft_patch import parse_quote_draft_patches

        price = parse_quote_draft_patches("PU皮按上次那个6.8")
        usage = parse_quote_draft_patches("600D牛津布每个用量改成0.56平方")
        included = parse_quote_draft_patches("肩带和固定带都加入正式BOM")
        excluded = parse_quote_draft_patches("箱子不参与报价")

        self.assertEqual(price["patches"], [{"op": "set_material_price", "material": "PU皮", "unit_price": 6.8}])
        self.assertEqual(usage["patches"], [{"op": "set_material_usage", "material": "600D牛津布", "usage": 0.56}])
        self.assertIn({"op": "set_material_included", "material": "肩带", "included": True}, included["patches"])
        self.assertIn({"op": "set_material_included", "material": "固定带", "included": True}, included["patches"])
        self.assertIn({"op": "set_material_included", "material": "箱子", "included": False}, excluded["patches"])

    def test_parse_tax_and_fob_phrases(self) -> None:
        from quote_draft_patch import parse_quote_draft_patches

        include_tax = parse_quote_draft_patches("这个客户要含税")
        exclude_tax = parse_quote_draft_patches("不含税")
        exclude_fob = parse_quote_draft_patches("EXW就行，不要FOB")
        include_fob = parse_quote_draft_patches("FOB也算进去")

        self.assertEqual(include_tax["patches"], [{"op": "set_include_tax", "include_tax": True}])
        self.assertEqual(exclude_tax["patches"], [{"op": "set_include_tax", "include_tax": False}])
        self.assertEqual(exclude_fob["patches"], [{"op": "set_include_fob", "include_fob": False}])
        self.assertEqual(include_fob["patches"], [{"op": "set_include_fob", "include_fob": True}])


    def test_rules_parse_without_calling_gpt(self) -> None:
        from quote_draft_patch import parse_quote_draft_patches

        with patch.dict("os.environ", {"QUOTE_DRAFT_GPT_PATCH_ENABLED": "1"}, clear=False), patch(
            "quote_draft_patch.parse_quote_draft_patches_by_gpt"
        ) as gpt:
            result = parse_quote_draft_patches("数量改300")

        self.assertEqual(result["intent"], "patch_draft")
        self.assertEqual(result["patches"], [{"op": "set_quantities", "quantities": [300]}])
        gpt.assert_not_called()

    def test_unknown_text_without_gpt_enabled_keeps_clarify(self) -> None:
        from quote_draft_patch import parse_quote_draft_patches

        with patch.dict("os.environ", {"QUOTE_DRAFT_GPT_PATCH_ENABLED": "0"}, clear=False), patch(
            "quote_draft_patch.parse_quote_draft_patches_by_gpt"
        ) as gpt:
            result = parse_quote_draft_patches("把那个软一点")

        self.assertEqual(result["intent"], "clarify")
        self.assertEqual(result["patches"], [])
        gpt.assert_not_called()

    def test_gpt_enabled_unknown_text_calls_gpt(self) -> None:
        from quote_draft_patch import parse_quote_draft_patches

        gpt_result = {
            "intent": "patch_draft",
            "patches": [{"op": "set_material_price", "material": "PU料", "unit_price": 6.5}],
            "assistant_message": "已理解为修改PU料单价。",
            "needs_recalculate": True,
        }
        with patch.dict("os.environ", {"QUOTE_DRAFT_GPT_PATCH_ENABLED": "1"}, clear=False), patch(
            "quote_draft_patch.parse_quote_draft_patches_by_gpt", return_value=gpt_result
        ) as gpt:
            result = parse_quote_draft_patches("PU那种料按六块五")

        self.assertEqual(result, gpt_result)
        gpt.assert_called_once()

    def test_validate_gpt_accepts_allowed_patch_types(self) -> None:
        from quote_draft_patch import validate_gpt_patch_response

        price = validate_gpt_patch_response(
            {
                "intent": "patch_draft",
                "patches": [{"op": "set_material_price", "material": "PU料", "unit_price": 6.5}],
                "assistant_message": "ok",
                "needs_recalculate": True,
            }
        )
        usage = validate_gpt_patch_response(
            {
                "intent": "patch_draft",
                "patches": [{"op": "set_material_usage", "material": "600D牛津布", "usage": 0.56}],
                "assistant_message": "ok",
                "needs_recalculate": True,
            }
        )
        included = validate_gpt_patch_response(
            {
                "intent": "patch_draft",
                "patches": [{"op": "set_material_included", "material": "肩带", "included": True}],
                "assistant_message": "ok",
                "needs_recalculate": True,
            }
        )

        self.assertEqual(price["patches"][0]["unit_price"], 6.5)
        self.assertEqual(usage["patches"][0]["usage"], 0.56)
        self.assertTrue(included["patches"][0]["included"])

    def test_validate_gpt_accepts_tax_and_fob_patch_types(self) -> None:
        from quote_draft_patch import validate_gpt_patch_response

        result = validate_gpt_patch_response(
            {
                "intent": "patch_draft",
                "patches": [
                    {"op": "set_include_tax", "include_tax": True},
                    {"op": "set_include_fob", "include_fob": False},
                ],
            }
        )

        self.assertEqual(
            result["patches"],
            [
                {"op": "set_include_tax", "include_tax": True},
                {"op": "set_include_fob", "include_fob": False},
            ],
        )

    def test_validate_gpt_margin_30_converts_to_rate(self) -> None:
        from quote_draft_patch import validate_gpt_patch_response

        result = validate_gpt_patch_response(
            {
                "intent": "patch_draft",
                "patches": [{"op": "set_margin", "gross_margin_rate": 30}],
                "assistant_message": "ok",
                "needs_recalculate": True,
            }
        )

        self.assertEqual(result["patches"], [{"op": "set_margin", "gross_margin_rate": 0.30}])

    def test_validate_gpt_confirm_and_recalculate_do_not_create_patches(self) -> None:
        from quote_draft_patch import validate_gpt_patch_response

        confirm = validate_gpt_patch_response({"intent": "confirm_save", "patches": []})
        recalc = validate_gpt_patch_response({"intent": "recalculate", "patches": []})

        self.assertEqual(confirm["intent"], "confirm_save")
        self.assertEqual(confirm["patches"], [])
        self.assertFalse(confirm["needs_recalculate"])
        self.assertEqual(recalc["intent"], "recalculate")
        self.assertEqual(recalc["patches"], [])
        self.assertTrue(recalc["needs_recalculate"])

    def test_validate_gpt_rejects_invalid_json_or_invalid_op(self) -> None:
        from quote_draft_patch import validate_gpt_patch_response

        invalid_json = validate_gpt_patch_response("not json")
        invalid_op = validate_gpt_patch_response(
            {"intent": "patch_draft", "patches": [{"op": "set_quote_result", "quote_result": {}}]}
        )

        self.assertEqual(invalid_json["intent"], "clarify")
        self.assertEqual(invalid_op["intent"], "clarify")

    def test_validate_gpt_rejects_fenced_json(self) -> None:
        from quote_draft_patch import validate_gpt_patch_response

        result = validate_gpt_patch_response(
            '```json\n{"intent":"patch_draft","patches":[{"op":"set_quantities","quantities":[300]}]}\n```'
        )

        self.assertEqual(result["intent"], "clarify")
        self.assertEqual(result["patches"], [])

    def test_validate_gpt_rejects_decimal_quantities(self) -> None:
        from quote_draft_patch import validate_gpt_patch_response

        decimal_number = validate_gpt_patch_response(
            {"intent": "patch_draft", "patches": [{"op": "set_quantities", "quantities": [3.5]}]}
        )
        decimal_string = validate_gpt_patch_response(
            {"intent": "patch_draft", "patches": [{"op": "set_quantities", "quantities": ["3.5"]}]}
        )

        self.assertEqual(decimal_number["intent"], "clarify")
        self.assertEqual(decimal_string["intent"], "clarify")

    def test_gpt_patch_always_needs_recalculate(self) -> None:
        from quote_draft_patch import validate_gpt_patch_response

        result = validate_gpt_patch_response(
            {
                "intent": "patch_draft",
                "patches": [{"op": "set_material_price", "material": "PU鏂?", "unit_price": 6.5}],
                "needs_recalculate": False,
            }
        )

        self.assertTrue(result["needs_recalculate"])

    def test_validate_gpt_rejects_forbidden_fields(self) -> None:
        from quote_draft_patch import validate_gpt_patch_response

        result = validate_gpt_patch_response(
            {
                "intent": "patch_draft",
                "patches": [{"op": "set_material_price", "material": "PU料", "unit_price": 6.5}],
                "quote_result": {"quote_id": "bad"},
            }
        )

        self.assertEqual(result["intent"], "clarify")
        self.assertEqual(result["patches"], [])

    def test_gpt_exception_returns_clarify(self) -> None:
        from quote_draft_patch import parse_quote_draft_patches

        with patch.dict("os.environ", {"QUOTE_DRAFT_GPT_PATCH_ENABLED": "1"}, clear=False), patch(
            "quote_draft_patch._call_gpt_patch_model", side_effect=RuntimeError("boom")
        ):
            result = parse_quote_draft_patches("帮我把特别那个料调一下")

        self.assertEqual(result["intent"], "clarify")
        self.assertEqual(result["patches"], [])


if __name__ == "__main__":
    unittest.main()
