import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


class FakePriceKB:
    def __init__(self, hits):
        self.hits = hits
        self.calls = []

    def lookup_ranked(self, name, spec="", *, limit=5, min_score=None):
        self.calls.append(
            {"name": name, "spec": spec, "limit": limit, "min_score": min_score}
        )
        return self.hits[:limit]


def make_hit(
    name="YKK拉链",
    spec="5#",
    price="7元/码",
    value=7.0,
    unit="码",
    score=0.82,
    auto_learned=False,
):
    entry = SimpleNamespace(
        raw_name=name,
        raw_spec=spec,
        raw_price=price,
        unit_price_value=value,
        unit_price_unit=unit,
        auto_learned=auto_learned,
    )
    return SimpleNamespace(entry=entry, score=score)


class McpPriceLookupTests(unittest.TestCase):
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
            else {"name": "YKK拉链", "spec": "5#", "limit": 5, "min_score": None},
        }

    def test_sales_with_valid_name_returns_hits(self):
        from mcp_server.tools.price_lookup import price_lookup

        fake_kb = FakePriceKB([make_hit()])
        with patch("price_kb.get_price_kb", return_value=fake_kb):
            result = price_lookup(self._input())

        self.assertTrue(result["ok"])
        self.assertEqual(result["tool"], "price_lookup")
        self.assertEqual(result["mode"], "readonly")
        self.assertEqual(result["result"]["hit_count"], 1)
        self.assertEqual(result["result"]["hits"][0]["name"], "YKK拉链")
        self.assertEqual(result["result"]["hits"][0]["unit_price_value"], 7.0)
        self.assertEqual(fake_kb.calls[0]["limit"], 5)

    def test_guest_role_returns_permission_error(self):
        from mcp_server.tools.price_lookup import price_lookup

        result = price_lookup(self._input(role="guest"))

        self.assertFalse(result["ok"])
        self.assertIn("无权", result["error"])

    def test_missing_query_name_returns_validation_error(self):
        from mcp_server.tools.price_lookup import price_lookup

        result = price_lookup(self._input(query={}))

        self.assertFalse(result["ok"])
        self.assertIn("name", result["error"])

    def test_call_writes_audit_log(self):
        from mcp_server.tools.price_lookup import price_lookup

        fake_kb = FakePriceKB([make_hit()])
        with patch("price_kb.get_price_kb", return_value=fake_kb):
            price_lookup(self._input())

        self.assertTrue(self.audit_path.exists())
        records = [
            json.loads(line)
            for line in self.audit_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertGreaterEqual(len(records), 1)
        self.assertEqual(records[-1]["tool"], "price_lookup")
        self.assertEqual(records[-1]["query_name"], "YKK拉链")
        self.assertEqual(records[-1]["role"], "sales")
        self.assertTrue(records[-1]["success"])
        self.assertIn("timestamp", records[-1])

    def test_no_hits_returns_ok_with_empty_hits(self):
        from mcp_server.tools.price_lookup import price_lookup

        fake_kb = FakePriceKB([])
        with patch("price_kb.get_price_kb", return_value=fake_kb):
            result = price_lookup(self._input(query={"name": "不存在材料"}))

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["hits"], [])
        self.assertEqual(result["result"]["hit_count"], 0)


if __name__ == "__main__":
    unittest.main()
