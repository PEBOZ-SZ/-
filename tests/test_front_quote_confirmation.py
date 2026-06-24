"""前台统一报价前确认流程的源码契约检查。"""

from __future__ import annotations

from pathlib import Path
import unittest


APP_JS = Path(__file__).resolve().parents[1] / "static" / "app.js"


def _app_js_text() -> str:
    return APP_JS.read_text(encoding="utf-8")


class FrontQuoteConfirmationContractTest(unittest.TestCase):
    def test_unified_preconfirm_page_uses_structure_preview_table(self) -> None:
        text = _app_js_text()
        self.assertIn("function buildStructureConfirmationHtml", text)
        self.assertIn('message.type === "structure_confirmation"', text)
        self.assertIn("function buildQuotePreConfirmSectionsHtml", text)
        self.assertIn("QUOTE_PRE_CONFIRM_SECTION_KEYS", text)

    def test_no_simplified_quote_confirm_table_ui(self) -> None:
        text = _app_js_text()
        self.assertNotIn("function buildQuoteConfirmationHtml", text)
        self.assertNotIn("quote-confirm-table", text)
        self.assertNotIn("class=\"btn-quote-confirm\"", text)

    def test_single_confirm_button_copy(self) -> None:
        text = _app_js_text()
        self.assertIn("确认并生成正式报价", text)
        self.assertNotIn("确认结构并开始报价", text)
        self.assertIn("data-quote-pre-confirm-submit", text)

    def test_no_second_confirmation_page_transition(self) -> None:
        text = _app_js_text()
        confirm_start = text.index("async function confirmAndGenerateQuote")
        confirm_chunk = text[confirm_start : confirm_start + 6000]
        self.assertIn("quote_confirmed: true", confirm_chunk)
        self.assertIn("structure_confirmed: true", confirm_chunk)
        self.assertIn("handleFinalQuoteConfirmationBlocked", confirm_chunk)
        self.assertNotIn("enterQuoteConfirmModeFromResult", confirm_chunk)

    def test_abcd_sections_rendered_on_preconfirm_page(self) -> None:
        text = _app_js_text()
        self.assertIn("buildQuotePreConfirmSectionsHtml", text)
        self.assertIn("${buildQuotePreConfirmSectionsHtml(data, tok", text)
        self.assertIn("报价前确认（A/B/C/D）", text)

    def test_material_detail_and_preview_share_pending_rows(self) -> None:
        text = _app_js_text()
        self.assertIn("function getMergedPendingStructureRows", text)
        self.assertIn("function syncPendingStructureRowsToData", text)
        self.assertIn("buildStructureMaterialDetailRows(data, pend)", text)
        save_start = text.index("function saveStructurePreviewEdits")
        save_chunk = text[save_start : save_start + 2500]
        self.assertIn("syncPendingStructureRowsToData(pend)", save_chunk)

    def test_confirm_payload_includes_edited_fields(self) -> None:
        text = _app_js_text()
        build_start = text.index("function buildStructureConfirmationItemsForQuote")
        build_chunk = text[build_start : build_start + 3500]
        self.assertIn("remark:", build_chunk)
        self.assertIn("section_key:", build_chunk)
        self.assertIn("included_in_quote:", build_chunk)
        self.assertIn('patch.source = "user_input"', build_chunk)
        self.assertIn('patch.usage_source = "user_input"', build_chunk)
        self.assertIn('patch.unit_price_source = "user_input"', build_chunk)
        self.assertIn('patch.amount_source = "user_input"', build_chunk)
        self.assertIn("delete patch.usage_ai", build_chunk)
        confirm_start = text.index("async function confirmAndGenerateQuote")
        confirm_chunk = text[confirm_start : confirm_start + 6000]
        self.assertIn("manual_requirement_fields", confirm_chunk)
        self.assertIn("buildManualRequirementFieldsFromPending", confirm_chunk)
        self.assertIn("payloadExtra.quantities", confirm_chunk)

    def test_confirm_quantity_falls_back_to_quote_params_f(self) -> None:
        text = _app_js_text()
        start = text.index("function getPendingQuoteQuantities")
        chunk = text[start : start + 2200]

        self.assertIn("quote_params?.F", chunk)
        self.assertIn("requirement_fields", chunk)
        self.assertIn("extractQuoteQuantitiesFromFieldMap", chunk)

    def test_incomplete_confirm_only_shows_text_hint(self) -> None:
        text = _app_js_text()
        fn_start = text.index("function handleFinalQuoteConfirmationBlocked")
        fn_chunk = text[fn_start : fn_start + 800]
        self.assertIn('type: "text"', fn_chunk)
        self.assertNotIn("enterQuoteConfirmModeFromResult", fn_chunk)

    def test_structure_confirm_renders_material_detail_section(self) -> None:
        text = _app_js_text()
        self.assertIn("function renderStructureMaterialDetailSection", text)
        self.assertIn("renderStructureMaterialDetailSection(data, tok", text)
        self.assertIn("材料明细", text)
        self.assertIn("展开核算", text)
        self.assertIn("material_piece_summaries", text)
        self.assertIn("<th>备注</th><th>区域</th><th>参与报价</th>", text)

    def test_material_detail_quantity_does_not_fallback_to_total_usage_for_piece_count(self) -> None:
        text = _app_js_text()
        start = text.index("function materialDetailRowQuantityText")
        chunk = text[start : start + 1800]
        self.assertNotIn("total_usage", chunk)
        self.assertNotIn("materialDetailTotalUsageText(summary, row)", chunk)

    def test_structure_preview_prefers_quote_confirmation_rows(self) -> None:
        text = _app_js_text()
        start = text.index("function getStructureConfirmationTableRows")
        chunk = text[start : start + 1200]
        self.assertIn("display_material_rows", chunk)
        self.assertLess(
            chunk.index("items_confirmation"),
            chunk.index("display_material_rows"),
        )

    def test_llm_permission_error_copy_says_local_parse_continues(self) -> None:
        text = _app_js_text()
        self.assertIn("AI补全不可用，已按表格/规则解析继续", text)
        self.assertIn("当前 Key 无权限调用该模型", text)

    def test_material_detail_uses_grouped_display_rows(self) -> None:
        text = _app_js_text()
        rows_start = text.index("function buildStructureMaterialDetailRows")
        rows_chunk = text[rows_start : rows_start + 2400]
        self.assertIn("display_material_rows", rows_chunk)
        self.assertIn("buildGroupedMaterialDetailRowsForDisplay", rows_chunk)
        self.assertLess(
            rows_chunk.index("display_material_rows"),
            rows_chunk.index("materials_detail_rows"),
        )
        lookup_start = text.index("function lookupMaterialPieceSummary")
        lookup_chunk = text[lookup_start : lookup_start + 900]
        self.assertIn("row?.material_piece_summary", lookup_chunk)

    def test_material_name_cell_does_not_render_parts_text(self) -> None:
        text = _app_js_text()
        start = text.index("function renderMaterialDetailRowGroupHtml")
        chunk = text[start : start + 1800]
        self.assertNotIn("partsHtml", chunk)
        self.assertNotIn("mat-detail-parts", chunk)
        self.assertNotIn("parts_text", chunk)
        self.assertIn('<span class="mat-detail-name">${name}</span>', chunk)

    def test_material_detail_quantity_never_falls_back_to_plain_none_text(self) -> None:
        text = _app_js_text()
        start = text.index("function materialDetailQuantityText")
        chunk = text[start : start + 1200]
        self.assertNotIn('return "无"', chunk)
        self.assertIn('return "缺少片数，待复核"', chunk)

    def test_piece_table_keeps_explicit_missing_quantity_and_subtotal(self) -> None:
        text = _app_js_text()
        start = text.index("function renderMaterialPieceTableRowHtml")
        chunk = text[start : start + 1800]
        self.assertNotIn('|| "无"', chunk)
        self.assertIn('"缺少片数"', chunk)
        self.assertIn('"缺少尺寸/片数"', chunk)
        self.assertIn('piece.quantity_display', chunk)
        self.assertIn('piece.subtotal_display', chunk)

    def test_frontend_grouped_rows_do_not_emit_multi_size_placeholder(self) -> None:
        text = _app_js_text()
        self.assertNotIn('"多尺寸"', text)
        start = text.index("function buildGroupedMaterialDetailRowsForDisplay")
        chunk = text[start : start + 2200]
        self.assertIn("sizes.join", chunk)


if __name__ == "__main__":
    unittest.main()
