import json
import unittest
from pathlib import Path
from unittest.mock import patch


class FakeToolCallingClient:
    def __init__(self, tool_names):
        self.tool_names = list(tool_names)
        self.calls = 0

    def create(self, messages, tools):
        self.calls += 1
        if self.calls <= len(self.tool_names):
            name = self.tool_names[self.calls - 1]
            return {
                "message": {
                    "tool_calls": [
                        {
                            "id": f"call_{self.calls}",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(self._arguments_for(name), ensure_ascii=False),
                            },
                        }
                    ]
                }
            }
        return {"message": {"content": "done"}}

    def _arguments_for(self, name):
        quote_result = {
            "product_name": "测试背包",
            "tiers": [{"quantity": 300, "exw_price": 88.9}],
            "total_price": 88.9,
        }
        if name == "quote_calculate":
            return {
                "user_context": {"user_id": "sales_001", "role": "sales", "session_id": "sess_gpt"},
                "payload": {
                    "product_name": "测试背包",
                    "quantities": [300],
                    "items": [{"name": "测试面料", "amount": 10}],
                },
            }
        if name == "quote_explain":
            return {
                "user_context": {"user_id": "sales_001", "role": "sales", "session_id": "sess_gpt"},
                "query": {
                    "user_question": "explain quote",
                    "quote_result": quote_result,
                    "audience": "sales_internal",
                },
            }
        if name == "quote_patch_preview":
            return {
                "user_context": {"user_id": "sales_001", "role": "sales", "session_id": "sess_gpt"},
                "query": {"quote_result": quote_result, "patch": {"processing_fee_delta": -0.5}},
            }
        if name == "quote_save":
            return {
                "user_context": {"user_id": "sales_001", "role": "sales", "session_id": "sess_gpt"},
                "query": {"quote_result": quote_result},
            }
        if name == "quote_export":
            return {
                "user_context": {"user_id": "sales_001", "role": "sales", "session_id": "sess_gpt"},
                "query": {"quote_id": "Q-20260124-0001"},
            }
        if name == "quote_admin":
            return {
                "user_context": {"user_id": "admin_001", "role": "admin", "session_id": "sess_gpt"},
                "query": {
                    "action": "approve_quote",
                    "quote_id": "Q-20260124-0001",
                    "payload": {"reason": "ok"},
                },
            }
        return {}


class GptToolRouterTests(unittest.TestCase):
    def setUp(self):
        self.trace_path = Path("logs/gpt_tool_trace.jsonl")
        if self.trace_path.exists():
            self.trace_path.unlink()

    def _patched_tools(self):
        return patch.multiple(
            "gpt_tool_router",
            quote_calculate=lambda data: {"ok": True, "tool": "quote_calculate", "data": data},
            quote_explain=lambda data: {"ok": True, "tool": "quote_explain", "data": data},
            quote_patch_preview=lambda data: {"ok": True, "tool": "quote_patch_preview", "data": data},
            quote_save=lambda data: {"ok": True, "tool": "quote_save", "data": data},
            quote_export=lambda data: {"ok": True, "tool": "quote_export", "data": data},
            quote_admin=lambda data: {"ok": True, "tool": "quote_admin", "data": data},
        )

    def _state_for_tool(self, tool_name):
        return {
            "quote_calculate": "CONFIRMED",
            "quote_save": "CALCULATED",
            "quote_export": "SAVED",
        }.get(tool_name, "INPUT")

    def _assert_routes_to(self, user_input, tool_name):
        from gpt_tool_router import run_gpt_tool_agent

        with self._patched_tools():
            result = run_gpt_tool_agent(
                user_input,
                context={"workflow_state": self._state_for_tool(tool_name)},
                client=FakeToolCallingClient([tool_name]),
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["tool_calls"][0]["tool_called"], tool_name)
        self.assertEqual(result["tool_calls"][0]["result"]["tool"], tool_name)

    def test_quote_input_routes_to_quote_calculate(self):
        self._assert_routes_to("做一个背包300个", "quote_calculate")

    def test_explain_input_routes_to_quote_explain(self):
        self._assert_routes_to("帮我解释报价", "quote_explain")

    def test_patch_input_routes_to_quote_patch_preview(self):
        self._assert_routes_to("太贵了优化一下", "quote_patch_preview")

    def test_save_input_routes_to_quote_save(self):
        self._assert_routes_to("保存报价", "quote_save")

    def test_export_input_routes_to_quote_export(self):
        self._assert_routes_to("导出报价", "quote_export")

    def test_admin_input_routes_to_quote_admin(self):
        self._assert_routes_to("审批报价", "quote_admin")

    def test_supports_multi_step_tool_chaining(self):
        from gpt_tool_router import run_gpt_tool_agent

        with self._patched_tools():
            result = run_gpt_tool_agent(
                "先报价再保存",
                context={"workflow_state": "CONFIRMED"},
                client=FakeToolCallingClient(["quote_calculate", "quote_save"]),
            )

        self.assertTrue(result["ok"])
        self.assertEqual(
            [call["tool_called"] for call in result["tool_calls"]],
            ["quote_calculate", "quote_save"],
        )

    def test_defines_openai_compatible_tool_schema(self):
        from gpt_tool_router import GPT_TOOL_SCHEMAS

        names = {tool["function"]["name"] for tool in GPT_TOOL_SCHEMAS}
        self.assertEqual(
            names,
            {
                "quote_calculate",
                "quote_explain",
                "quote_patch_preview",
                "quote_save",
                "quote_export",
                "quote_admin",
            },
        )
        for tool in GPT_TOOL_SCHEMAS:
            self.assertEqual(tool["type"], "function")
            self.assertIn("description", tool["function"])
            self.assertIn("parameters", tool["function"])

    def test_writes_gpt_tool_trace(self):
        from gpt_tool_router import run_gpt_tool_agent

        with self._patched_tools():
            run_gpt_tool_agent(
                "保存报价",
                context={"workflow_state": "CALCULATED"},
                client=FakeToolCallingClient(["quote_save"]),
            )

        records = [
            json.loads(line)
            for line in self.trace_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        latest = records[-1]
        self.assertEqual(latest["user_input"], "保存报价")
        self.assertEqual(latest["tool_called"], "quote_save")
        self.assertIn("gpt_decision", latest)
        self.assertIn("tool_arguments", latest)
        self.assertIn("result", latest)
        self.assertTrue(latest["success"])

    def test_does_not_use_agent_router_or_quote_engine(self):
        from gpt_tool_router import run_gpt_tool_agent

        with self._patched_tools(), patch("agent_router.run_agent") as rule_agent, patch(
            "quote_engine.calculate_quote"
        ) as engine, patch("quotation_agent.calculator_bridge.run_calculate_quote") as bridge:
            result = run_gpt_tool_agent(
                "保存报价",
                context={"workflow_state": "CALCULATED"},
                client=FakeToolCallingClient(["quote_save"]),
            )

        self.assertTrue(result["ok"])
        rule_agent.assert_not_called()
        engine.assert_not_called()
        bridge.assert_not_called()


if __name__ == "__main__":
    unittest.main()
