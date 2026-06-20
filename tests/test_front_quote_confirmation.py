"""前台 quote_confirmation 阶段仍复用结构/明细预览表格的源码契约检查。"""

from __future__ import annotations

from pathlib import Path
import unittest


APP_JS = Path(__file__).resolve().parents[1] / "static" / "app.js"


def _app_js_text() -> str:
    return APP_JS.read_text(encoding="utf-8")


class FrontQuoteConfirmationContractTest(unittest.TestCase):
    def test_quote_confirmation_uses_structure_preview_table(self) -> None:
        text = _app_js_text()
        self.assertIn("function buildStructureConfirmationHtml", text)
        self.assertIn('message.type === "structure_confirmation"', text)
        self.assertIn("enterQuoteConfirmModeFromResult", text)
        self.assertIn("quoteConfirmMode", text)

    def test_no_simplified_quote_confirm_table_ui(self) -> None:
        text = _app_js_text()
        self.assertNotIn("function buildQuoteConfirmationHtml", text)
        self.assertNotIn("quote-confirm-table", text)
        self.assertNotIn("class=\"btn-quote-confirm\"", text)

    def test_final_confirm_button_not_handled_by_structure_confirm(self) -> None:
        text = _app_js_text()
        final_idx = text.index("[data-quote-confirm-submit]")
        structure_handler_idx = text.index(
            'event.target.closest(".btn-structure-confirm")'
        )
        self.assertLess(final_idx, structure_handler_idx)
        self.assertIn("!scBtn.hasAttribute(\"data-quote-confirm-submit\")", text)
        self.assertIn("function confirmFinalQuoteFromStructureTable", text)

    def test_final_confirm_payload_contract(self) -> None:
        text = _app_js_text()
        fn_start = text.index("async function confirmFinalQuoteFromStructureTable")
        fn_chunk = text[fn_start : fn_start + 4500]
        self.assertIn("quote_confirmed: true", fn_chunk)
        self.assertIn("quote_confirmed_by_user: true", fn_chunk)
        self.assertIn("buildStructureConfirmationItemsForQuote(pending)", fn_chunk)

    def test_structure_confirm_handles_quote_confirmation_before_http_error(self) -> None:
        text = _app_js_text()
        fn_start = text.index("async function confirmStructureAndQuote")
        fn_chunk = text[fn_start : fn_start + 4500]
        quote_check = fn_chunk.index("isQuoteConfirmationResult(result)")
        http_check = fn_chunk.index("if (!response.ok)")
        self.assertLess(quote_check, http_check)

    def test_is_quote_confirmation_ignores_successful_quote_metadata(self) -> None:
        text = _app_js_text()
        fn_start = text.index("function isQuoteConfirmationResult")
        fn_chunk = text[fn_start : fn_start + 500]
        self.assertIn("quote_ready === true", fn_chunk)
        self.assertNotIn("result.quote_confirmation && typeof result.quote_confirmation", fn_chunk)

    def test_final_confirm_does_not_reenter_confirmation_page(self) -> None:
        text = _app_js_text()
        fn_start = text.index("async function confirmFinalQuoteFromStructureTable")
        fn_chunk = text[fn_start : fn_start + 3500]
        self.assertIn("handleFinalQuoteConfirmationBlocked", fn_chunk)
        self.assertNotIn("enterQuoteConfirmModeFromResult", fn_chunk)

    def test_structure_confirm_renders_material_detail_section(self) -> None:
        text = _app_js_text()
        self.assertIn("function renderStructureMaterialDetailSection", text)
        self.assertIn("${renderStructureMaterialDetailSection(data, tok)}", text)
        self.assertIn("材料明细", text)
        self.assertIn("展开核算", text)
        self.assertIn("material_piece_summaries", text)
        self.assertIn("material_area_overview", text)
        self.assertIn("<th>类型</th><th>材料名</th><th>尺寸</th><th>总用量</th><th>数量</th><th>损耗</th>", text)
        self.assertIn("buildStructureConfirmationItemsForQuote(pending)", text)


if __name__ == "__main__":
    unittest.main()
