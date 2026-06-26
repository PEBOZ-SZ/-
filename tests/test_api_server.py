import json
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


class ApiServerTests(unittest.TestCase):
    def setUp(self):
        self.trace_path = Path("logs/api_trace.jsonl")
        if self.trace_path.exists():
            self.trace_path.unlink()

    def test_chat_uses_gpt_tool_router(self):
        from api_server import app

        fake_result = {
            "ok": True,
            "tool_calls": [
                {
                    "tool_called": "quote_calculate",
                    "tool_arguments": {"payload": {"product_name": "测试背包"}},
                    "result": {"ok": True, "tool": "quote_calculate", "result": {"total_price": 123.45}},
                }
            ],
            "final_message": "ok",
        }
        with patch("gpt_client.run_chat", return_value=fake_result) as run_chat:
            client = TestClient(app)
            response = client.post(
                "/chat",
                json={"message": "做一个背包300个", "user_id": "u001", "session_id": "s001"},
            )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["tool_trace"], ["quote_calculate"])
        self.assertEqual(data["result"]["total_price"], 123.45)
        run_chat.assert_called_once()

    def test_quote_calculate_endpoint_calls_mcp_bridge(self):
        from api_server import app

        with patch("mcp_bridge.call_mcp_tool", return_value={"ok": True, "tool": "quote_calculate"}) as call:
            client = TestClient(app)
            response = client.post(
                "/quote/calculate",
                json={
                    "user_context": {"user_id": "u001", "role": "sales", "session_id": "s001"},
                    "query": {"workflow_state": "CONFIRMED"},
                    "payload": {"items": [{"name": "测试面料"}]},
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        call.assert_called_once()
        self.assertEqual(call.call_args.args[0], "quote_calculate")
        self.assertEqual(call.call_args.args[1]["workflow_state"], "CONFIRMED")

    def test_quote_save_endpoint_calls_mcp_bridge(self):
        from api_server import app

        with patch("mcp_bridge.call_mcp_tool", return_value={"ok": True, "tool": "quote_save"}) as call:
            client = TestClient(app)
            response = client.post(
                "/quote/save",
                json={
                    "user_context": {"user_id": "u001", "role": "sales", "session_id": "s001"},
                    "query": {"workflow_state": "CALCULATED", "quote_result": {"product_name": "测试背包"}},
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(call.call_args.args[0], "quote_save")

    def test_quote_export_endpoint_calls_mcp_bridge(self):
        from api_server import app

        with patch("mcp_bridge.call_mcp_tool", return_value={"ok": True, "tool": "quote_export"}) as call:
            client = TestClient(app)
            response = client.post(
                "/quote/export",
                json={
                    "user_context": {"user_id": "u001", "role": "sales", "session_id": "s001"},
                    "query": {"workflow_state": "SAVED", "quote_id": "Q-20260124-0001"},
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(call.call_args.args[0], "quote_export")

    def test_quote_admin_endpoint_calls_mcp_bridge(self):
        from api_server import app

        with patch("mcp_bridge.call_mcp_tool", return_value={"ok": True, "tool": "quote_admin"}) as call:
            client = TestClient(app)
            response = client.post(
                "/quote/admin",
                json={
                    "user_context": {"user_id": "admin_001", "role": "admin", "session_id": "s001"},
                    "query": {
                        "action": "approve_quote",
                        "quote_id": "Q-20260124-0001",
                        "payload": {"reason": "ok"},
                    },
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(call.call_args.args[0], "quote_admin")

    def test_api_trace_is_written(self):
        from api_server import app

        with patch("mcp_bridge.call_mcp_tool", return_value={"ok": True, "tool": "quote_save"}):
            client = TestClient(app)
            response = client.post(
                "/quote/save",
                json={
                    "user_context": {"user_id": "u001", "role": "sales", "session_id": "s001"},
                    "query": {"workflow_state": "CALCULATED", "quote_result": {"product_name": "测试背包"}},
                },
            )

        self.assertTrue(response.json()["ok"])
        records = [
            json.loads(line)
            for line in self.trace_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        latest = records[-1]
        self.assertEqual(latest["tool_called"], "quote_save")
        self.assertIn("request_body", latest)
        self.assertIn("response", latest)

    def test_calculate_without_structure_confirm_returns_flow_error(self):
        from api_server import app

        client = TestClient(app)
        response = client.post(
            "/quote/calculate",
            json={
                "user_context": {"user_id": "u001", "role": "sales", "session_id": "s001"},
                "workflow_state": "STRUCTURE_CONFIRM",
                "payload": {"items": [{"name": "测试面料"}]},
            },
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertFalse(data["ok"])
        self.assertEqual(data["error"], "FLOW_ERROR: 请先完成 STRUCTURE_CONFIRM")

    def test_structure_confirm_endpoint_moves_to_confirmed(self):
        from api_server import app

        client = TestClient(app)
        response = client.post(
            "/workflow/structure-confirm",
            json={"session_id": "s001", "state": "STRUCTURE_CONFIRM", "action": "ignored"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(response.json()["state"], "CONFIRMED")


if __name__ == "__main__":
    unittest.main()
