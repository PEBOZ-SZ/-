import unittest
from unittest.mock import patch


class OrchestratorArchitectureTests(unittest.TestCase):
    def test_mcp_router_uses_tool_registry(self):
        import mcp_router

        calls = []

        def fake_tool(args):
            calls.append(args)
            return {"ok": True, "tool": "fake_tool"}

        with patch.dict(mcp_router.TOOL_REGISTRY, {"fake_tool": fake_tool}, clear=True):
            result = mcp_router.mcp_call("fake_tool", {"x": 1})

        self.assertTrue(result["ok"])
        self.assertEqual(calls, [{"x": 1}])

    def test_mcp_router_rejects_unregistered_tool(self):
        import mcp_router

        with patch.dict(mcp_router.TOOL_REGISTRY, {}, clear=True):
            result = mcp_router.mcp_call("missing_tool", {})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "unsupported MCP tool: missing_tool")

    def test_orchestrator_process_runs_multi_step_plan(self):
        import orchestrator

        seen_states = []

        def fake_gpt(payload, state):
            seen_states.append(state)
            return {
                "task": "generate_quote",
                "plan": [
                    {
                        "step": 1,
                        "tool": "quote_calculate",
                        "args": {"workflow_state": "CONFIRMED", "payload": {"items": [{"name": "测试面料"}]}},
                    },
                    {
                        "step": 2,
                        "tool": "quote_save",
                        "args": {"workflow_state": "CALCULATED", "query": {"quote_result": "$steps.1.result"}},
                    },
                ],
            }

        calls = []

        def fake_mcp_call(tool, args):
            calls.append((tool, args))
            if tool == "quote_calculate":
                return {"ok": True, "tool": tool, "result": {"total_price": 123.45}}
            return {"ok": True, "tool": tool, "result": {"quote_id": "Q-1"}}

        with patch("orchestrator.decide_with_gpt", side_effect=fake_gpt), patch(
            "orchestrator.mcp_router.mcp_call",
            side_effect=fake_mcp_call,
        ):
            result = orchestrator.process({"message": "做一个背包300个", "workflow_state": "CONFIRMED"})

        self.assertTrue(result["ok"])
        self.assertEqual(result["workflow"], ["intake", "parse", "tool_select", "execute", "assemble", "response"])
        self.assertEqual(result["task"], "generate_quote")
        self.assertEqual(result["tool_trace"], ["quote_calculate", "quote_save"])
        self.assertEqual(result["result"]["quote_id"], "Q-1")
        self.assertEqual(result["context"]["steps"]["1"]["result"]["total_price"], 123.45)
        self.assertEqual(calls[1][1]["query"]["quote_result"], {"total_price": 123.45})
        self.assertEqual(seen_states, ["parse"])

    def test_orchestrator_rejects_non_json_gpt_decision(self):
        import orchestrator

        with patch("orchestrator.decide_with_gpt", return_value="直接报价 88 元"):
            result = orchestrator.process({"message": "做一个背包300个"})

        self.assertFalse(result["ok"])
        self.assertEqual(result["state"], "response")
        self.assertIn("GPT plan must be JSON object", result["error"])

    def test_orchestrator_rejects_single_tool_protocol(self):
        import orchestrator

        with patch("orchestrator.decide_with_gpt", return_value={"intent": "chat", "tool": "", "args": {}}), patch(
            "orchestrator.mcp_router.mcp_call"
        ) as mcp_call:
            result = orchestrator.process({"message": "你好"})

        self.assertFalse(result["ok"])
        self.assertIn("plan", result["error"])
        mcp_call.assert_not_called()

    def test_orchestrator_validates_ordered_plan_steps(self):
        import orchestrator

        bad_plan = {
            "task": "generate_quote",
            "plan": [
                {"step": 2, "tool": "quote_save", "args": {}},
                {"step": 1, "tool": "quote_calculate", "args": {}},
            ],
        }
        with patch("orchestrator.decide_with_gpt", return_value=bad_plan):
            result = orchestrator.process({"message": "报价"})

        self.assertFalse(result["ok"])
        self.assertIn("ordered", result["error"])

    def test_server_exposes_orchestrator_endpoint(self):
        import server

        self.assertTrue(hasattr(server, "process_with_orchestrator"))
        with patch("server.orchestrator.process", return_value={"ok": True, "result": {"hello": "world"}}) as proc:
            result = server.process_with_orchestrator({"message": "hello"})

        self.assertTrue(result["ok"])
        proc.assert_called_once_with({"message": "hello"})


if __name__ == "__main__":
    unittest.main()
