import json
import unittest
from pathlib import Path
from unittest.mock import patch


class McpQuoteQaTests(unittest.TestCase):
    def setUp(self):
        self.audit_path = Path("logs/mcp_audit.jsonl")
        if self.audit_path.exists():
            self.audit_path.unlink()

    def _input(self, role="sales", query=None):
        return {
            "user_context": {
                "user_id": "sales_001",
                "user_name": "张三",
                "role": role,
                "session_id": "sess_001",
            },
            "query": query
            if query is not None
            else {"user_text": "客户嫌这个包贵，怎么解释？"},
        }

    def test_sales_with_valid_user_text_calls_answer_qa(self):
        from mcp_server.tools.quote_qa import quote_qa

        with patch("qa_rag.answer_qa") as answer_qa:
            answer_qa.return_value = {
                "assistant_message": "可以先解释材料和工艺成本。",
                "source_type": "llm",
                "sources": [{"title": "safe"}],
                "qa_sources": [],
                "debug": "hidden",
            }

            result = quote_qa(self._input())

        self.assertTrue(result["ok"])
        self.assertEqual(result["tool"], "quote_qa")
        self.assertEqual(result["mode"], "readonly")
        self.assertEqual(result["result"]["answer"], "可以先解释材料和工艺成本。")
        self.assertNotIn("debug", result["result"])
        answer_qa.assert_called_once_with("客户嫌这个包贵，怎么解释？", sid="sess_001")

    def test_guest_role_returns_permission_error(self):
        from mcp_server.tools.quote_qa import quote_qa

        result = quote_qa(self._input(role="guest", query={"user_text": "600D牛津布是什么？"}))

        self.assertFalse(result["ok"])
        self.assertIn("无权", result["error"])

    def test_missing_user_text_returns_validation_error(self):
        from mcp_server.tools.quote_qa import quote_qa

        result = quote_qa(self._input(query={}))

        self.assertFalse(result["ok"])
        self.assertIn("user_text", result["error"])

    def test_write_or_formal_quote_intent_is_blocked_without_calling_answer_qa(self):
        from mcp_server.tools.quote_qa import quote_qa

        with patch("qa_rag.answer_qa") as answer_qa:
            result = quote_qa(self._input(query={"user_text": "帮我重新报价并保存"}))

        self.assertFalse(result["ok"])
        self.assertTrue("只读" in result["error"] or "quote_qa" in result["error"])
        answer_qa.assert_not_called()

    def test_call_writes_audit_log_without_full_user_text(self):
        from mcp_server.tools.quote_qa import quote_qa

        user_text = "客户嫌这个包贵，怎么解释？"
        with patch("qa_rag.answer_qa") as answer_qa:
            answer_qa.return_value = {"answer": "建议解释成本结构。", "source_type": "fallback"}
            quote_qa(self._input(query={"user_text": user_text}))

        self.assertTrue(self.audit_path.exists())
        records = [
            json.loads(line)
            for line in self.audit_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertGreaterEqual(len(records), 1)
        latest = records[-1]
        self.assertEqual(latest["tool"], "quote_qa")
        self.assertEqual(latest["role"], "sales")
        self.assertTrue(latest["success"])
        self.assertEqual(latest["text_length"], len(user_text))
        self.assertIn("timestamp", latest)
        self.assertNotIn("user_text", latest)
        self.assertNotIn(user_text, json.dumps(latest, ensure_ascii=False))

    def test_sanitizer_hides_internal_fields(self):
        from mcp_server.sanitizer import sanitize_quote_qa_result

        result = sanitize_quote_qa_result(
            {
                "answer": "可以这样解释。",
                "source_type": "llm",
                "sources": [],
                "qa_sources": [],
                "prompt": "hidden",
                "raw_messages": ["hidden"],
                "token": "hidden",
                "debug": "hidden",
            }
        )

        self.assertEqual(result["answer"], "可以这样解释。")
        self.assertNotIn("prompt", result)
        self.assertNotIn("raw_messages", result)
        self.assertNotIn("token", result)
        self.assertNotIn("debug", result)


if __name__ == "__main__":
    unittest.main()
