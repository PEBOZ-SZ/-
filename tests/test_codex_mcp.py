import json
import subprocess
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class CodexMcpServerTests(unittest.TestCase):
    def test_registered_tools_are_visible(self):
        from mcp_server.codex_mcp import TOOL_REGISTRY

        self.assertEqual(
            set(TOOL_REGISTRY),
            {
                "quote_calculate",
                "price_lookup",
                "quote_qa",
                "quote_explain",
                "quote_patch_preview",
                "quote_save",
                "quote_export",
                "quote_admin",
            },
        )

    def test_stdio_initialize_tools_list_and_quote_calculate(self):
        client = _StdioMcpClient()
        try:
            initialize = client.request(
                "initialize",
                {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "unittest", "version": "0.1.0"},
                },
            )
            self.assertIn("serverInfo", initialize["result"])

            client.notify("notifications/initialized")

            tools_list = client.request("tools/list", {})
            tool_names = {tool["name"] for tool in tools_list["result"]["tools"]}
            self.assertEqual(
                tool_names,
                {
                    "quote_calculate",
                    "price_lookup",
                    "quote_qa",
                    "quote_explain",
                    "quote_patch_preview",
                    "quote_save",
                    "quote_export",
                    "quote_admin",
                },
            )

            quote_result = client.request(
                "tools/call",
                {
                    "name": "quote_calculate",
                    "arguments": {
                        "input_data": {
                            "user_context": {
                                "user_id": "sales_stdio",
                                "role": "sales",
                                "session_id": "stdio_test",
                            },
                            "payload": {
                                "product_name": "MCP测试背包",
                                "items": [{"name": "测试面料", "amount": 10}],
                            },
                        }
                    },
                },
            )
            self.assertFalse(quote_result["result"].get("isError", False), quote_result)
            content = quote_result["result"]["content"][0]
            text = content.get("text", "")
            self.assertIn('"ok": true', text)
            self.assertIn('"tool": "quote_calculate"', text)
        finally:
            client.close()


class _StdioMcpClient:
    def __init__(self):
        self._next_id = 1
        self._process = subprocess.Popen(
            [sys.executable, "-m", "mcp_server.codex_mcp"],
            cwd=PROJECT_ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    def request(self, method, params):
        request_id = self._next_id
        self._next_id += 1
        self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        return self._read_response(request_id)

    def notify(self, method, params=None):
        self._write({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def close(self):
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=5)
        if self._process.stdin:
            self._process.stdin.close()
        if self._process.stdout:
            self._process.stdout.close()
        if self._process.stderr:
            self._process.stderr.close()

    def _write(self, payload):
        assert self._process.stdin is not None
        self._process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self._process.stdin.flush()

    def _read_response(self, request_id):
        assert self._process.stdout is not None
        for _ in range(50):
            line = self._process.stdout.readline()
            if line:
                response = json.loads(line)
                if response.get("id") == request_id:
                    return response
                continue
            if self._process.poll() is not None:
                stderr = self._process.stderr.read() if self._process.stderr else ""
                raise AssertionError(f"MCP process exited early with stderr: {stderr}")
        raise AssertionError(f"Timed out waiting for MCP response id={request_id}")


if __name__ == "__main__":
    unittest.main()
