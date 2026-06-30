from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def sample_payload(risk_flags=None):
    return {
        "product_name": "测试包",
        "quantities": [500],
        "processing_fee": 10,
        "gross_margin_rate": 0.25,
        "include_fob": True,
        "items": [
            {"name": "PU料", "usage": "0.5平方", "unit_price": "6元", "amount": 3},
            {"name": "肩带", "usage": "1条", "unit_price": "2元", "amount": 2, "included_in_quote": False},
        ],
        "risk_flags": list(risk_flags or []),
    }


class QuoteAgentApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.store_path = Path(self.tmpdir.name) / "quote_drafts.json"
        self.store_patch = patch("quote_draft_store.DRAFT_STORE_PATH", self.store_path)
        self.store_patch.start()

    def tearDown(self) -> None:
        self.store_patch.stop()
        self.tmpdir.cleanup()

    def test_creates_draft_from_payload(self) -> None:
        import server

        with patch.object(
            server,
            "quote_calculate",
            return_value={"ok": True, "result": {"quote_id": "calc-create", "tiers": [{"quantity": 500}]}},
        ):
            result = server.handle_quote_agent_request(
                {
                    "session_id": "sess-create",
                    "message": "重新计算",
                    "payload": sample_payload(),
                }
            )

        self.assertEqual(result["type"], "quote_updated")
        self.assertEqual(result["draft"]["product_name"], "测试包")

    def test_creates_empty_session_draft_without_payload_or_calculation(self) -> None:
        import server
        from quote_draft_store import get_quote_draft

        with patch.object(server, "quote_calculate") as calc, patch.object(server, "quote_save") as save:
            result = server.handle_quote_agent_request(
                {"session_id": "sess-empty-create", "message": "这个再看看"}
            )

        self.assertEqual(result["type"], "clarify")
        self.assertIsNotNone(result["draft"])
        self.assertEqual(result["draft"]["session_id"], "sess-empty-create")
        self.assertIsNotNone(get_quote_draft("sess-empty-create"))
        calc.assert_not_called()
        save.assert_not_called()

    def test_quantity_patch_updates_draft_and_recalculates_with_existing_tool(self) -> None:
        import server

        calc = Mock(return_value={"ok": True, "result": {"quote_id": "calc-1", "tiers": [{"quantity": 300}]}})
        with patch.object(server, "quote_calculate", calc):
            result = server.handle_quote_agent_request(
                {
                    "session_id": "sess-agent-1",
                    "message": "数量改300",
                    "payload": sample_payload(),
                }
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["type"], "quote_updated")
        self.assertEqual(result["draft"]["quantities"], [300])
        self.assertEqual(result["quote_result"]["tiers"][0]["quantity"], 300)
        calc.assert_called_once()
        attempted = calc.call_args.args[0]["payload"]
        self.assertEqual(attempted["quantities"], [300])

    def test_margin_patch_updates_gross_margin_rate(self) -> None:
        import server

        with patch.object(
            server,
            "quote_calculate",
            return_value={"ok": True, "result": {"quote_id": "calc-margin", "tiers": [{"quantity": 500}]}},
        ):
            result = server.handle_quote_agent_request(
                {
                    "session_id": "sess-margin",
                    "message": "毛利改30%",
                    "payload": sample_payload(),
                }
            )

        self.assertEqual(result["type"], "quote_updated")
        self.assertEqual(result["draft"]["gross_margin_rate"], 0.30)

    def test_include_tax_patch_updates_draft_and_recalculates(self) -> None:
        import server

        calc = Mock(return_value={"ok": True, "result": {"quote_id": "calc-tax", "tiers": [{"quantity": 500}]}})
        with patch.object(server, "quote_calculate", calc):
            result = server.handle_quote_agent_request(
                {
                    "session_id": "sess-tax",
                    "message": "这个客户要含税",
                    "payload": sample_payload(),
                }
            )

        self.assertEqual(result["type"], "quote_updated")
        self.assertTrue(result["draft"]["include_tax"])
        calc.assert_called_once()
        self.assertTrue(calc.call_args.args[0]["payload"]["include_tax"])

    def test_include_fob_patch_updates_draft_and_recalculates(self) -> None:
        import server

        calc = Mock(return_value={"ok": True, "result": {"quote_id": "calc-fob", "tiers": [{"quantity": 500}]}})
        with patch.object(server, "quote_calculate", calc):
            result = server.handle_quote_agent_request(
                {
                    "session_id": "sess-fob",
                    "message": "EXW就行，不要FOB",
                    "payload": sample_payload(),
                }
            )

        self.assertEqual(result["type"], "quote_updated")
        self.assertFalse(result["draft"]["include_fob"])
        calc.assert_called_once()
        self.assertFalse(calc.call_args.args[0]["payload"]["include_fob"])

    def test_multi_quantity_patch_recalculates_with_all_tiers(self) -> None:
        import server

        calc = Mock(return_value={"ok": True, "result": {"quote_id": "calc-multi", "tiers": [{"quantity": 500}, {"quantity": 1000}]}})
        with patch.object(server, "quote_calculate", calc):
            result = server.handle_quote_agent_request(
                {
                    "session_id": "sess-multi",
                    "message": "数量改成500和1000两档",
                    "payload": sample_payload(),
                }
            )

        self.assertEqual(result["type"], "quote_updated")
        self.assertEqual(result["draft"]["quantities"], [500, 1000])
        self.assertEqual(calc.call_args.args[0]["payload"]["quantities"], [500, 1000])

    def test_material_price_patch_updates_draft(self) -> None:
        import server

        with patch.object(
            server,
            "quote_calculate",
            return_value={"ok": True, "result": {"quote_id": "calc-2", "tiers": [{"quantity": 500}]}},
        ):
            result = server.handle_quote_agent_request(
                {
                    "session_id": "sess-agent-2",
                    "message": "PU料按6.5",
                    "payload": sample_payload(),
                }
            )

        self.assertEqual(result["type"], "quote_updated")
        self.assertEqual(result["draft"]["items"][0]["unit_price"], 6.5)

    def test_clarify_does_not_modify_or_recalculate(self) -> None:
        import server
        from quote_draft_store import create_quote_draft, get_quote_draft

        create_quote_draft("sess-agent-3", source_payload=sample_payload())
        before = get_quote_draft("sess-agent-3")

        with patch.object(server, "quote_calculate") as calc:
            result = server.handle_quote_agent_request(
                {"session_id": "sess-agent-3", "message": "这个再看看"}
            )

        self.assertEqual(result["type"], "clarify")
        self.assertEqual(get_quote_draft("sess-agent-3")["updated_at"], before["updated_at"])
        calc.assert_not_called()

    def test_confirm_save_blocks_when_risk_flags_remain(self) -> None:
        import server
        from quote_draft_store import create_quote_draft

        create_quote_draft("sess-agent-4", source_payload=sample_payload(["肩带是否加入正式BOM"]))

        with patch.object(server, "quote_save") as save:
            result = server.handle_quote_agent_request(
                {"session_id": "sess-agent-4", "message": "确认保存"}
            )

        self.assertEqual(result["type"], "clarify")
        save.assert_not_called()

    def test_confirm_save_after_risk_resolved_calls_existing_save_and_pending(self) -> None:
        import server
        from quote_draft_store import create_quote_draft, update_quote_draft

        create_quote_draft(
            "sess-agent-5",
            source_payload=sample_payload(["肩带是否加入正式BOM"]),
            quote_result={"quote_id": "calc-5", "quote_series_uid": "series-5", "tiers": [{"quantity": 500}]},
        )
        update_quote_draft(
            "sess-agent-5",
            [{"op": "set_material_included", "material": "肩带", "included": True}],
        )
        save = Mock(return_value={"ok": True, "result": {"quote_id": "calc-5", "status": "saved"}})

        with patch.object(server, "quote_save", save):
            result = server.handle_quote_agent_request(
                {"session_id": "sess-agent-5", "message": "确认保存"}
            )

        self.assertEqual(result["type"], "saved")
        self.assertEqual(result["draft"]["source_quote_result"]["approval_status"], "pending")
        save.assert_called_once()

    def test_gpt_patch_is_accepted_then_existing_calculate_runs(self) -> None:
        import server

        calc = Mock(return_value={"ok": True, "result": {"quote_id": "calc-gpt", "tiers": [{"quantity": 500}]}})
        gpt_raw = {
            "intent": "patch_draft",
            "patches": [{"op": "set_material_price", "material": "PU料", "unit_price": 6.5}],
            "assistant_message": "已理解为修改PU料单价。",
            "needs_recalculate": True,
        }
        with patch.dict("os.environ", {"QUOTE_DRAFT_GPT_PATCH_ENABLED": "1"}, clear=False), patch(
            "quote_draft_patch._call_gpt_patch_model", return_value=__import__("json").dumps(gpt_raw, ensure_ascii=False)
        ), patch.object(server, "quote_calculate", calc):
            result = server.handle_quote_agent_request(
                {
                    "session_id": "sess-agent-gpt",
                    "message": "PU那种料按六块五",
                    "payload": sample_payload(),
                }
            )

        self.assertEqual(result["type"], "quote_updated")
        self.assertEqual(result["draft"]["items"][0]["unit_price"], 6.5)
        self.assertEqual(result["quote_result"]["quote_id"], "calc-gpt")
        calc.assert_called_once()

    def test_gpt_patch_with_tax_and_fob_ops_runs_existing_calculate(self) -> None:
        import server

        calc = Mock(return_value={"ok": True, "result": {"quote_id": "calc-gpt-fob", "tiers": [{"quantity": 500}]}})
        gpt_raw = {
            "intent": "patch_draft",
            "patches": [
                {"op": "set_include_tax", "include_tax": True},
                {"op": "set_include_fob", "include_fob": False},
            ],
            "assistant_message": "ok",
        }
        with patch.dict("os.environ", {"QUOTE_DRAFT_GPT_PATCH_ENABLED": "1"}, clear=False), patch(
            "quote_draft_patch._call_gpt_patch_model", return_value=__import__("json").dumps(gpt_raw, ensure_ascii=False)
        ), patch.object(server, "quote_calculate", calc):
            result = server.handle_quote_agent_request(
                {
                    "session_id": "sess-agent-gpt-tax-fob",
                    "message": "客户含税，EXW就行",
                    "payload": sample_payload(),
                }
            )

        self.assertEqual(result["type"], "quote_updated")
        self.assertTrue(result["draft"]["include_tax"])
        self.assertFalse(result["draft"]["include_fob"])
        calc.assert_called_once()

    def test_gpt_patch_cannot_disable_existing_calculate(self) -> None:
        import server

        calc = Mock(return_value={"ok": True, "result": {"quote_id": "calc-forced", "tiers": [{"quantity": 500}]}})
        gpt_raw = {
            "intent": "patch_draft",
            "patches": [{"op": "set_material_price", "material": "PU鏂?", "unit_price": 6.5}],
            "assistant_message": "ok",
            "needs_recalculate": False,
        }
        with patch.dict("os.environ", {"QUOTE_DRAFT_GPT_PATCH_ENABLED": "1"}, clear=False), patch(
            "quote_draft_patch._call_gpt_patch_model", return_value=__import__("json").dumps(gpt_raw, ensure_ascii=False)
        ), patch.object(server, "quote_calculate", calc):
            result = server.handle_quote_agent_request(
                {
                    "session_id": "sess-agent-gpt-force-calc",
                    "message": "PU閭ｇ鏂欐寜鍏潡浜?",
                    "payload": sample_payload(),
                }
            )

        self.assertEqual(result["type"], "quote_updated")
        self.assertEqual(result["quote_result"]["quote_id"], "calc-forced")
        calc.assert_called_once()

    def test_gpt_patch_does_not_directly_generate_quote_result(self) -> None:
        import server

        calc = Mock(return_value={"ok": True, "result": {"quote_id": "calc-only", "tiers": [{"quantity": 500}]}})
        gpt_raw = {
            "intent": "patch_draft",
            "patches": [{"op": "set_material_usage", "material": "PU料", "usage": 0.66}],
            "assistant_message": "已理解为修改PU料用量。",
            "needs_recalculate": True,
        }
        with patch.dict("os.environ", {"QUOTE_DRAFT_GPT_PATCH_ENABLED": "1"}, clear=False), patch(
            "quote_draft_patch._call_gpt_patch_model", return_value=__import__("json").dumps(gpt_raw, ensure_ascii=False)
        ), patch.object(server, "quote_calculate", calc):
            result = server.handle_quote_agent_request(
                {
                    "session_id": "sess-agent-gpt-no-result",
                    "message": "PU用量稍微改一下",
                    "payload": sample_payload(),
                }
            )

        self.assertEqual(result["quote_result"], {"quote_id": "calc-only", "tiers": [{"quantity": 500}]})
        self.assertNotIn("quote_result", gpt_raw)
        calc.assert_called_once()

    def test_gpt_failure_does_not_modify_draft_or_recalculate(self) -> None:
        import server
        from quote_draft_store import create_quote_draft, get_quote_draft

        create_quote_draft("sess-agent-gpt-fail", source_payload=sample_payload())
        before = get_quote_draft("sess-agent-gpt-fail")
        with patch.dict("os.environ", {"QUOTE_DRAFT_GPT_PATCH_ENABLED": "1"}, clear=False), patch(
            "quote_draft_patch._call_gpt_patch_model", side_effect=RuntimeError("boom")
        ), patch.object(server, "quote_calculate") as calc:
            result = server.handle_quote_agent_request(
                {"session_id": "sess-agent-gpt-fail", "message": "把那个软一点"}
            )

        self.assertEqual(result["type"], "clarify")
        self.assertEqual(get_quote_draft("sess-agent-gpt-fail")["updated_at"], before["updated_at"])
        calc.assert_not_called()


if __name__ == "__main__":
    unittest.main()
