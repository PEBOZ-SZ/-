import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class McpQuoteAdminTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.store_path = Path(self.tmpdir.name) / "mcp_saved_quotes.jsonl"
        self.rules_path = Path(self.tmpdir.name) / "mcp_price_rules_admin.jsonl"
        self.audit_path = Path("logs/mcp_audit.jsonl")
        if self.audit_path.exists():
            self.audit_path.unlink()
        self.quote_id = "Q-20260124-0001"
        self._write_quote(status="saved", frozen=False)

    def tearDown(self):
        self.tmpdir.cleanup()

    def _write_quote(self, status="saved", frozen=False):
        record = {
            "quote_id": self.quote_id,
            "created_at": "2026-01-24T10:00:00",
            "user_id": "sales_001",
            "role": "sales",
            "session_id": "sess_001",
            "status": status,
            "locked": True,
            "frozen": frozen,
            "quote_result": {
                "product_name": "测试背包",
                "quote_id": self.quote_id,
                "locked": True,
                "tiers": [{"quantity": 300, "exw_price": 88.9}],
                "total_price": 88.9,
            },
        }
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.store_path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")

    def _input(self, role="admin", action="approve_quote", quote_id=None, payload=None):
        return {
            "user_context": {
                "user_id": "admin_001" if role == "admin" else "sales_001",
                "role": role,
                "session_id": "sess_001",
            },
            "query": {
                "action": action,
                "quote_id": quote_id if quote_id is not None else self.quote_id,
                "payload": payload or {"reason": "价格合理"},
            },
        }

    def _patch_paths(self):
        return patch.multiple(
            "mcp_server.tools.quote_admin",
            QUOTE_SAVE_STORE_PATH=self.store_path,
            QUOTE_ADMIN_PRICE_RULE_PATH=self.rules_path,
        )

    def _latest_record(self):
        lines = [line for line in self.store_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return json.loads(lines[-1])

    def test_admin_approve_saved_to_approved(self):
        from mcp_server.tools.quote_admin import quote_admin

        with self._patch_paths():
            result = quote_admin(self._input(action="approve_quote"))

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["status"], "approved")
        self.assertEqual(self._latest_record()["status"], "approved")

    def test_admin_mark_approved_to_exported(self):
        from mcp_server.tools.quote_admin import quote_admin

        self._write_quote(status="approved", frozen=False)

        with self._patch_paths():
            result = quote_admin(self._input(action="mark_exported"))

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["status"], "exported")
        self.assertEqual(self._latest_record()["status"], "exported")

    def test_cannot_export_draft_or_saved_directly(self):
        from mcp_server.tools.quote_admin import quote_admin

        with self._patch_paths():
            self._write_quote(status="draft", frozen=False)
            draft = quote_admin(self._input(action="mark_exported"))
            self._write_quote(status="saved", frozen=False)
            saved = quote_admin(self._input(action="mark_exported"))

        self.assertFalse(draft["ok"])
        self.assertFalse(saved["ok"])
        self.assertIn("approved", draft["error"])
        self.assertIn("approved", saved["error"])

    def test_cannot_approve_exported(self):
        from mcp_server.tools.quote_admin import quote_admin

        self._write_quote(status="exported", frozen=False)

        with self._patch_paths():
            result = quote_admin(self._input(action="approve_quote"))

        self.assertFalse(result["ok"])
        self.assertIn("exported", result["error"])

    def test_admin_reject_quote_success(self):
        from mcp_server.tools.quote_admin import quote_admin

        with self._patch_paths():
            result = quote_admin(self._input(action="reject_quote"))

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["status"], "rejected")
        self.assertEqual(self._latest_record()["status"], "rejected")

    def test_freeze_does_not_change_status(self):
        from mcp_server.tools.quote_admin import quote_admin

        self._write_quote(status="approved", frozen=False)

        with self._patch_paths():
            result = quote_admin(self._input(action="freeze_quote"))

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["status"], "approved")
        latest = self._latest_record()
        self.assertEqual(latest["status"], "approved")
        self.assertTrue(latest["frozen"])

    def test_unfreeze_does_not_change_status(self):
        from mcp_server.tools.quote_admin import quote_admin

        self._write_quote(status="rejected", frozen=True)

        with self._patch_paths():
            result = quote_admin(self._input(action="unfreeze_quote"))

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["status"], "rejected")
        latest = self._latest_record()
        self.assertEqual(latest["status"], "rejected")
        self.assertFalse(latest["frozen"])

    def test_view_quote_returns_exported_status(self):
        from mcp_server.tools.quote_admin import quote_admin

        self._write_quote(status="exported", frozen=False)
        before = self.store_path.read_text(encoding="utf-8")

        with self._patch_paths():
            result = quote_admin(self._input(role="sales", action="view_quote"))

        after = self.store_path.read_text(encoding="utf-8")
        self.assertTrue(result["ok"])
        self.assertEqual(result["result"]["status"], "exported")
        self.assertIn("quote_summary", result["result"])
        self.assertEqual(before, after)

    def test_admin_freeze_and_unfreeze_success(self):
        from mcp_server.tools.quote_admin import quote_admin

        with self._patch_paths():
            frozen = quote_admin(self._input(action="freeze_quote"))
            unfrozen = quote_admin(self._input(action="unfreeze_quote"))

        self.assertTrue(frozen["ok"])
        self.assertTrue(frozen["result"]["frozen"])
        self.assertTrue(unfrozen["ok"])
        self.assertFalse(unfrozen["result"]["frozen"])
        self.assertFalse(self._latest_record()["frozen"])

    def test_sales_can_only_view_quote(self):
        from mcp_server.tools.quote_admin import quote_admin

        with self._patch_paths():
            view = quote_admin(self._input(role="sales", action="view_quote"))
            approve = quote_admin(self._input(role="sales", action="approve_quote"))

        self.assertTrue(view["ok"])
        self.assertEqual(view["result"]["action"], "view_quote")
        self.assertFalse(approve["ok"])
        self.assertIn("无权", approve["error"])

    def test_guest_is_denied(self):
        from mcp_server.tools.quote_admin import quote_admin

        with self._patch_paths():
            result = quote_admin(self._input(role="guest", action="view_quote"))

        self.assertFalse(result["ok"])
        self.assertIn("无权", result["error"])

    def test_update_price_rule_admin_only_and_does_not_touch_price_kb(self):
        from mcp_server.tools.quote_admin import quote_admin

        with self._patch_paths(), patch("price_kb.get_price_kb") as get_price_kb:
            admin = quote_admin(
                self._input(
                    role="admin",
                    action="update_price_rule",
                    quote_id="",
                    payload={"rule": "拉链价格需复核"},
                )
            )
            sales = quote_admin(
                self._input(
                    role="sales",
                    action="update_price_rule",
                    quote_id="",
                    payload={"rule": "不允许"},
                )
            )

        self.assertTrue(admin["ok"])
        self.assertEqual(admin["result"]["status"], "rule_updated")
        self.assertTrue(self.rules_path.exists())
        self.assertFalse(sales["ok"])
        get_price_kb.assert_not_called()

    def test_does_not_call_quote_engine(self):
        from mcp_server.tools.quote_admin import quote_admin

        with self._patch_paths(), patch("quote_engine.calculate_quote") as engine, patch(
            "quotation_agent.calculator_bridge.run_calculate_quote"
        ) as bridge:
            result = quote_admin(self._input(action="approve_quote"))

        self.assertTrue(result["ok"])
        engine.assert_not_called()
        bridge.assert_not_called()

    def test_audit_log_records_action_without_quote_result(self):
        from mcp_server.tools.quote_admin import quote_admin

        with self._patch_paths():
            quote_admin(self._input(action="approve_quote"))

        records = [
            json.loads(line)
            for line in self.audit_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        latest = records[-1]
        self.assertEqual(latest["tool"], "quote_admin")
        self.assertEqual(latest["action"], "approve_quote")
        self.assertEqual(latest["quote_id"], self.quote_id)
        self.assertEqual(latest["status"], "approved")
        self.assertTrue(latest["success"])
        self.assertNotIn("quote_result", json.dumps(latest, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
