import json
import unittest
from pathlib import Path
from unittest.mock import patch


class McpQuoteExplainTests(unittest.TestCase):
    def setUp(self):
        self.audit_path = Path("logs/mcp_audit.jsonl")
        if self.audit_path.exists():
            self.audit_path.unlink()

    def _quote_result(self):
        return {
            "product_name": "测试背包",
            "material_total": 100,
            "material_total_text": "100元",
            "tiers": [
                {
                    "quantity": 300,
                    "cost_before_margin": 55.2,
                    "exw_price": 84.9,
                    "fob_price": 88.9,
                    "margin_rate": 0.35,
                },
                {
                    "quantity": 1000,
                    "cost_before_margin": 48.6,
                    "exw_price": 74.8,
                    "fob_price": 78.8,
                    "margin_rate": 0.35,
                },
            ],
            "items": [
                {
                    "name": "测试面料",
                    "spec": "600D",
                    "usage": "1码",
                    "unit_price": "10元/码",
                    "amount": 10,
                    "debug": "hidden",
                }
            ],
            "warnings": [],
            "review_required": False,
            "debug": "hidden",
        }

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
            else {
                "user_question": "为什么 300 件比 1000 件贵？",
                "quote_result": self._quote_result(),
                "audience": "sales_internal",
            },
        }

    def test_sales_with_quote_result_returns_llm_explanation(self):
        from mcp_server.tools.quote_explain import quote_explain

        with patch("quotation_agent.moonshot_client.chat_completions") as llm:
            llm.return_value = "300 件价格更高，主要因为固定费用摊到单件更多。"

            result = quote_explain(self._input())

        self.assertTrue(result["ok"])
        self.assertEqual(result["tool"], "quote_explain")
        self.assertEqual(result["mode"], "readonly")
        self.assertTrue(result["result"]["answer"])
        self.assertTrue(result["result"]["used_quote_result"])
        self.assertEqual(result["result"]["number_policy"], "quote_result_only")
        self.assertFalse(result["result"]["fallback_used"])
        llm.assert_called_once()

    def test_guest_role_returns_permission_error(self):
        from mcp_server.tools.quote_explain import quote_explain

        result = quote_explain(self._input(role="guest"))

        self.assertFalse(result["ok"])
        self.assertIn("无权", result["error"])

    def test_missing_quote_result_returns_validation_error(self):
        from mcp_server.tools.quote_explain import quote_explain

        result = quote_explain(self._input(query={"user_question": "这个报价为什么贵？"}))

        self.assertFalse(result["ok"])
        self.assertIn("quote_result", result["error"])

    def test_missing_user_question_returns_validation_error(self):
        from mcp_server.tools.quote_explain import quote_explain

        result = quote_explain(self._input(query={"quote_result": self._quote_result()}))

        self.assertFalse(result["ok"])
        self.assertIn("user_question", result["error"])

    def test_write_or_requote_intent_is_blocked_without_llm_or_calculator(self):
        from mcp_server.tools.quote_explain import quote_explain

        query = {
            "user_question": "帮我重新报价并保存",
            "quote_result": self._quote_result(),
        }
        with patch("quotation_agent.moonshot_client.chat_completions") as llm, patch(
            "quote_engine.calculate_quote"
        ) as engine, patch(
            "quotation_agent.calculator_bridge.run_calculate_quote"
        ) as bridge:
            result = quote_explain(self._input(query=query))

        self.assertFalse(result["ok"])
        self.assertTrue("只解释" in result["error"] or "quote_explain" in result["error"])
        llm.assert_not_called()
        engine.assert_not_called()
        bridge.assert_not_called()

    def test_llm_failure_falls_back_to_local_explanation(self):
        from mcp_server.tools.quote_explain import quote_explain

        with patch("quotation_agent.moonshot_client.chat_completions") as llm:
            llm.side_effect = RuntimeError("missing key")

            result = quote_explain(self._input())

        self.assertTrue(result["ok"])
        self.assertTrue(result["result"]["fallback_used"])
        self.assertTrue(result["result"]["answer"])

    def test_sanitizer_hides_internal_fields(self):
        from mcp_server.sanitizer import sanitize_quote_explain_result

        result = sanitize_quote_explain_result(
            {
                "answer": "解释文本",
                "audience": "sales_internal",
                "used_quote_result": True,
                "number_policy": "quote_result_only",
                "fallback_used": False,
                "quote_result": {"debug": "hidden"},
                "quote_result_facts": {"debug": "hidden"},
                "prompt": "hidden",
                "raw_messages": ["hidden"],
                "token": "hidden",
                "debug": "hidden",
            }
        )

        self.assertEqual(result["answer"], "解释文本")
        self.assertNotIn("quote_result", result)
        self.assertNotIn("quote_result_facts", result)
        self.assertNotIn("prompt", result)
        self.assertNotIn("raw_messages", result)
        self.assertNotIn("token", result)
        self.assertNotIn("debug", result)

    def test_call_writes_audit_log_without_question_or_quote_result(self):
        from mcp_server.tools.quote_explain import quote_explain

        question = "为什么 300 件比 1000 件贵？"
        quote_result = self._quote_result()
        with patch("quotation_agent.moonshot_client.chat_completions") as llm:
            llm.return_value = "固定费用摊销导致小数量更贵。"
            quote_explain(
                self._input(
                    query={
                        "user_question": question,
                        "quote_result": quote_result,
                        "audience": "factory_review",
                    }
                )
            )

        self.assertTrue(self.audit_path.exists())
        records = [
            json.loads(line)
            for line in self.audit_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        latest = records[-1]
        self.assertEqual(latest["tool"], "quote_explain")
        self.assertEqual(latest["role"], "sales")
        self.assertEqual(latest["audience"], "factory_review")
        self.assertTrue(latest["success"])
        self.assertEqual(latest["text_length"], len(question))
        self.assertEqual(latest["tier_count"], 2)
        self.assertEqual(latest["item_count"], 1)
        self.assertTrue(latest["quote_result_present"])
        self.assertIn("timestamp", latest)
        serialized = json.dumps(latest, ensure_ascii=False)
        self.assertNotIn(question, serialized)
        self.assertNotIn("测试面料", serialized)
        self.assertNotIn("material_total", serialized)
        self.assertNotIn("tiers", serialized)
        self.assertNotIn("items", serialized)


if __name__ == "__main__":
    unittest.main()
