import json
import unittest
from pathlib import Path
from unittest.mock import patch


class AgentRouterTests(unittest.TestCase):
    def setUp(self):
        self.trace_path = Path("logs/agent_trace.jsonl")
        if self.trace_path.exists():
            self.trace_path.unlink()
        self.context = {
            "user_context": {
                "user_id": "sales_001",
                "role": "sales",
                "session_id": "sess_agent_001",
            },
            "quote_result": {
                "product_name": "测试背包",
                "tiers": [{"quantity": 300, "exw_price": 88.9}],
                "total_price": 88.9,
            },
            "quote_id": "Q-20260124-0001",
        }

    def _patched_tools(self):
        return patch.multiple(
            "agent_router",
            quote_calculate=lambda data: {"ok": True, "tool": "quote_calculate", "data": data},
            quote_explain=lambda data: {"ok": True, "tool": "quote_explain", "data": data},
            quote_patch_preview=lambda data: {"ok": True, "tool": "quote_patch_preview", "data": data},
            quote_save=lambda data: {"ok": True, "tool": "quote_save", "data": data},
            quote_export=lambda data: {"ok": True, "tool": "quote_export", "data": data},
            quote_admin=lambda data: {"ok": True, "tool": "quote_admin", "data": data},
        )

    def test_quote_input_routes_to_quote_calculate(self):
        from agent_router import run_agent

        with self._patched_tools():
            result = run_agent("做一个背包300个", self.context)

        self.assertEqual(result["intent"], "quote")
        self.assertEqual(result["tool_called"], "quote_calculate")
        self.assertEqual(result["result"]["tool"], "quote_calculate")

    def test_explain_input_routes_to_quote_explain(self):
        from agent_router import run_agent

        with self._patched_tools():
            result = run_agent("帮我解释这个报价", self.context)

        self.assertEqual(result["intent"], "explain")
        self.assertEqual(result["tool_called"], "quote_explain")

    def test_patch_input_routes_to_quote_patch_preview(self):
        from agent_router import run_agent

        with self._patched_tools():
            result = run_agent("太贵了降一点", self.context)

        self.assertEqual(result["intent"], "patch")
        self.assertEqual(result["tool_called"], "quote_patch_preview")

    def test_save_input_routes_to_quote_save(self):
        from agent_router import run_agent

        with self._patched_tools():
            result = run_agent("保存报价", self.context)

        self.assertEqual(result["intent"], "save")
        self.assertEqual(result["tool_called"], "quote_save")

    def test_export_input_routes_to_quote_export(self):
        from agent_router import run_agent

        with self._patched_tools():
            result = run_agent("导出报价", self.context)

        self.assertEqual(result["intent"], "export")
        self.assertEqual(result["tool_called"], "quote_export")

    def test_admin_input_routes_to_quote_admin(self):
        from agent_router import run_agent

        context = dict(self.context)
        context["user_context"] = {
            "user_id": "admin_001",
            "role": "admin",
            "session_id": "sess_agent_001",
        }
        with self._patched_tools():
            result = run_agent("审批报价", context)

        self.assertEqual(result["intent"], "admin")
        self.assertEqual(result["tool_called"], "quote_admin")

    def test_writes_agent_trace_without_full_result(self):
        from agent_router import run_agent

        with self._patched_tools():
            result = run_agent("保存报价", self.context)

        self.assertTrue(result["result"]["ok"])
        records = [
            json.loads(line)
            for line in self.trace_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        latest = records[-1]
        self.assertEqual(latest["user_input"], "保存报价")
        self.assertEqual(latest["intent"], "save")
        self.assertEqual(latest["tool_called"], "quote_save")
        self.assertTrue(latest["success"])
        self.assertNotIn("quote_result", latest)

    def test_agent_does_not_call_quote_engine(self):
        from agent_router import run_agent

        with self._patched_tools(), patch("quote_engine.calculate_quote") as engine, patch(
            "quotation_agent.calculator_bridge.run_calculate_quote"
        ) as bridge:
            result = run_agent("保存报价", self.context)

        self.assertTrue(result["result"]["ok"])
        engine.assert_not_called()
        bridge.assert_not_called()


if __name__ == "__main__":
    unittest.main()
