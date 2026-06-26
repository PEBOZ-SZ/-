import json
import unittest
from pathlib import Path
from unittest.mock import patch


class WorkflowStateManagerTests(unittest.TestCase):
    def setUp(self):
        self.log_path = Path("logs/workflow_trace.jsonl")
        if self.log_path.exists():
            self.log_path.unlink()

    def test_blocks_quote_calculate_before_structure_confirm(self):
        from workflow_state_manager import FLOW_ERROR_STRUCTURE_CONFIRM, validate_tool_call

        with self.assertRaises(PermissionError) as ctx:
            validate_tool_call("quote_calculate", {"workflow_state": "STRUCTURE_CONFIRM"})

        self.assertEqual(str(ctx.exception), FLOW_ERROR_STRUCTURE_CONFIRM)

    def test_allows_quote_calculate_only_when_confirmed(self):
        from workflow_state_manager import validate_tool_call

        validate_tool_call("quote_calculate", {"workflow_state": "CONFIRMED"})

    def test_save_requires_calculated_and_export_requires_saved(self):
        from workflow_state_manager import FLOW_ERROR_STRUCTURE_CONFIRM, validate_tool_call

        with self.assertRaises(PermissionError) as save_ctx:
            validate_tool_call("quote_save", {"workflow_state": "CONFIRMED"})
        with self.assertRaises(PermissionError) as export_ctx:
            validate_tool_call("quote_export", {"workflow_state": "CALCULATED"})

        self.assertEqual(str(save_ctx.exception), FLOW_ERROR_STRUCTURE_CONFIRM)
        self.assertEqual(str(export_ctx.exception), FLOW_ERROR_STRUCTURE_CONFIRM)
        validate_tool_call("quote_save", {"workflow_state": "CALCULATED"})
        validate_tool_call("quote_export", {"workflow_state": "SAVED"})

    def test_transition_sequence_is_strict(self):
        from workflow_state_manager import transition_state

        state = "INPUT"
        state = transition_state(state, "gpt_parse_structure")
        self.assertEqual(state, "PARSED")
        state = transition_state(state, "show_structure_confirm")
        self.assertEqual(state, "STRUCTURE_CONFIRM")
        state = transition_state(state, "user_confirm_structure")
        self.assertEqual(state, "CONFIRMED")
        state = transition_state(state, "quote_calculate")
        self.assertEqual(state, "CALCULATED")
        state = transition_state(state, "quote_save")
        self.assertEqual(state, "SAVED")
        state = transition_state(state, "quote_export")
        self.assertEqual(state, "EXPORTED")

    def test_blocks_illegal_transition(self):
        from workflow_state_manager import FLOW_ERROR_STRUCTURE_CONFIRM, transition_state

        with self.assertRaises(PermissionError) as ctx:
            transition_state("INPUT", "quote_calculate")

        self.assertEqual(str(ctx.exception), FLOW_ERROR_STRUCTURE_CONFIRM)

    def test_logs_state_tool_gpt_and_user_actions(self):
        from workflow_state_manager import log_workflow_event

        log_workflow_event("state transition", session_id="s001", state="PARSED")
        log_workflow_event("gpt action", session_id="s001", state="PARSED", detail={"action": "parse"})
        log_workflow_event("tool call", session_id="s001", state="CONFIRMED", tool="quote_calculate")
        log_workflow_event("user action", session_id="s001", state="STRUCTURE_CONFIRM", detail={"action": "confirm"})

        records = [
            json.loads(line)
            for line in self.log_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual([r["event"] for r in records], ["state transition", "gpt action", "tool call", "user action"])

    def test_mcp_bridge_blocks_early_calculate(self):
        import mcp_bridge

        with patch.dict(mcp_bridge.MCP_TOOL_MAP, {"quote_calculate": lambda data: {"ok": True}}):
            result = mcp_bridge.call_mcp_tool("quote_calculate", {"workflow_state": "STRUCTURE_CONFIRM"})

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "FLOW_ERROR: 请先完成 STRUCTURE_CONFIRM")

    def test_gpt_tool_router_blocks_gpt_early_quote_calculate(self):
        from tests.test_gpt_tool_router import FakeToolCallingClient
        from gpt_tool_router import run_gpt_tool_agent

        with patch("gpt_tool_router.quote_calculate", return_value={"ok": True}) as calc:
            result = run_gpt_tool_agent(
                "做一个背包300个",
                context={"workflow_state": "STRUCTURE_CONFIRM"},
                client=FakeToolCallingClient(["quote_calculate"]),
            )

        self.assertFalse(result["ok"])
        self.assertIn("FLOW_ERROR", result["tool_calls"][0]["result"]["error"])
        calc.assert_not_called()


if __name__ == "__main__":
    unittest.main()
