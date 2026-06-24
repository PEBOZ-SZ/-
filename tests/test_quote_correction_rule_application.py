"""纠错规则审批与应用。"""

from __future__ import annotations

import json
import sqlite3
import unittest

from quote_correction_candidate_pool import (
    approve_correction_candidate,
    insert_correction_candidate,
    rule_row_extended_match,
)
from quote_correction_learning import (
    LEARNED_RULE_ID_PREFIX,
    RULE_SOURCE_ADMIN_APPROVED,
    RULE_STATUS_APPROVED,
    RULE_STATUS_PENDING,
    apply_quote_applicable_rules_to_payload,
    init_correction_learning_storage,
    load_quote_applicable_rules,
    set_test_connection,
)
from quote_engine import calculate_quote


class RuleApplicationDbTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        set_test_connection(self.conn)
        init_correction_learning_storage()

    def tearDown(self) -> None:
        set_test_connection(None)
        self.conn.close()

    def _insert_pending_rule(self, rule_id: str) -> None:
        now = "2026-01-01T00:00:00Z"
        self.conn.execute(
            """
            INSERT INTO quote_correction_rules (
                rule_id, rule_type, field_name, match_keywords, match_product_keywords,
                match_structure_keywords, bad_values, corrected_value, confidence, source_count,
                enabled, affects_calculation, created_at, updated_at, reason,
                rule_status, auto_learned, rule_source
            ) VALUES (?, 'usage_correction', 'usage', '["DCF"]', '["收纳包"]', '["立体收纳包"]',
                '["0.32码"]', '0.13码', 0.85, 1, 0, 1, ?, ?, 'pending rule', ?, 1, 'correction_candidate')
            """,
            (rule_id, now, now, RULE_STATUS_PENDING),
        )
        self.conn.commit()

    def test_pending_rule_not_in_applicable_rules(self) -> None:
        rid = f"{LEARNED_RULE_ID_PREFIX}pending-test"
        self._insert_pending_rule(rid)
        applicable = {r.rule_id for r in load_quote_applicable_rules()}
        self.assertNotIn(rid, applicable)

    def test_approve_candidate_creates_enabled_rule(self) -> None:
        cid = insert_correction_candidate(
            quote_uid="q-dcf",
            product_name="小型DCF立体收纳包",
            product_type="收纳包",
            material_name="DCF外料",
            material_spec="DCF",
            structure_text="立体收纳包，无肩带，无提手，无外袋，四周包边",
            system_usage="0.32码",
            corrected_usage="0.13码",
            system_unit_price="24.5/码",
            corrected_unit_price="24.5/码",
            error_type="usage_overestimated",
            reason="DCF小包外料用量高估",
            suggested_rule={
                "rule_type": "usage_correction",
                "field_name": "usage",
                "corrected_value": "0.13码",
                "match_keywords": ["DCF", "DCF外料"],
                "match_product_keywords": ["收纳包"],
                "match_structure_keywords": ["立体收纳包", "无肩带", "无提手", "无外袋", "四周包边"],
                "product_type_pattern": "收纳包",
                "size_condition_json": {"max_l_cm": 25, "max_w_cm": 20, "max_h_cm": 15},
            },
            evidence={"old_usage": "0.32码", "new_usage": "0.13码"},
        )
        result = approve_correction_candidate(cid, reviewed_by="admin", review_note="DCF小包确认")
        self.assertTrue(result.get("ok"))
        rule_id = result.get("rule_id")
        self.assertTrue(rule_id)
        applicable = {r.rule_id: r for r in load_quote_applicable_rules()}
        self.assertIn(rule_id, applicable)
        row = self.conn.execute(
            "SELECT rule_status, enabled, rule_source FROM quote_correction_rules WHERE rule_id = ?",
            (rule_id,),
        ).fetchone()
        self.assertEqual(row["rule_status"], RULE_STATUS_APPROVED)
        self.assertEqual(int(row["enabled"]), 1)
        self.assertEqual(row["rule_source"], RULE_SOURCE_ADMIN_APPROVED)
        cand = self.conn.execute(
            "SELECT status FROM quote_correction_candidates WHERE candidate_id = ?",
            (cid,),
        ).fetchone()
        self.assertEqual(cand["status"], "approved")

    def _insert_dcf_approved_rule(self, rule_id: str | None = None) -> str:
        rid = rule_id or f"{LEARNED_RULE_ID_PREFIX}dcf-active"
        now = "2026-01-01T00:00:00Z"
        self.conn.execute(
            """
            INSERT INTO quote_correction_rules (
                rule_id, rule_type, field_name, match_keywords, match_product_keywords,
                match_structure_keywords, bad_values, corrected_value, confidence, source_count,
                enabled, affects_calculation, created_at, updated_at, reason,
                rule_status, auto_learned, rule_source, approved_by, approved_at,
                product_type_pattern, size_condition_json, rule_payload_json
            ) VALUES (?, 'usage_correction', 'usage', '["DCF","DCF外料"]', '["收纳包"]',
                '["立体收纳包","无肩带"]', '["0.32码"]', '0.13码', 0.9, 1, 1, 1, ?, ?,
                'DCF小包修正', ?, 1, ?, 'admin', ?, '收纳包', ?,
                ?)
            """,
            (
                rid,
                now,
                now,
                RULE_STATUS_APPROVED,
                RULE_SOURCE_ADMIN_APPROVED,
                now,
                json.dumps({"max_l_cm": 25, "max_w_cm": 20, "max_h_cm": 15}, ensure_ascii=False),
                json.dumps(
                    {
                        "product_type_pattern": "收纳包",
                        "size_condition_json": {"max_l_cm": 25, "max_w_cm": 20, "max_h_cm": 15},
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        self.conn.commit()
        return rid

    def _dcf_payload(self, **overrides) -> dict:
        payload = {
            "product_name": "小型DCF立体收纳包",
            "product_type": "收纳包",
            "structure_text": "立体收纳包，无肩带，无提手",
            "product_size": {"LCM": 20, "WCM": 15, "HCM": 8},
            "items": [
                {
                    "name": "DCF外料",
                    "spec": "DCF",
                    "usage": "0.32码",
                    "unit_price": "400元/码",
                    "amount": 128.0,
                }
            ],
            "quantities": [300],
            "processing_fee": 5,
            "mold_fee": 0,
            "gross_margin_rate": 0.35,
        }
        payload.update(overrides)
        return payload

    def test_disabled_rule_not_applied(self) -> None:
        rid = f"{LEARNED_RULE_ID_PREFIX}disabled"
        now = "2026-01-01T00:00:00Z"
        self.conn.execute(
            """
            INSERT INTO quote_correction_rules (
                rule_id, rule_type, field_name, match_keywords, match_product_keywords,
                match_structure_keywords, bad_values, corrected_value, confidence, source_count,
                enabled, affects_calculation, created_at, updated_at, reason,
                rule_status, auto_learned, rule_source, approved_by, approved_at
            ) VALUES (?, 'usage_correction', 'usage', '["DCF"]', '[]', '[]', '[]', '0.13码', 0.9, 1,
                0, 1, ?, ?, 'disabled', ?, 1, ?, 'admin', ?)
            """,
            (rid, now, now, RULE_STATUS_APPROVED, RULE_SOURCE_ADMIN_APPROVED, now),
        )
        self.conn.commit()
        payload = self._dcf_payload()
        apply_quote_applicable_rules_to_payload(payload)
        self.assertEqual(payload["items"][0]["usage"], "0.32码")

    def test_pending_rule_not_applied_on_normal_bom_payload(self) -> None:
        rid = f"{LEARNED_RULE_ID_PREFIX}pending-dcf"
        now = "2026-01-01T00:00:00Z"
        self.conn.execute(
            """
            INSERT INTO quote_correction_rules (
                rule_id, rule_type, field_name, match_keywords, match_product_keywords,
                match_structure_keywords, bad_values, corrected_value, confidence, source_count,
                enabled, affects_calculation, created_at, updated_at, reason,
                rule_status, auto_learned, rule_source
            ) VALUES (?, 'usage_correction', 'usage', '["DCF","DCF外料"]', '["收纳包"]',
                '["立体收纳包"]', '["0.32码"]', '0.13码', 0.85, 1, 0, 1, ?, ?, 'pending', ?, 1, ?)
            """,
            (rid, now, now, RULE_STATUS_PENDING, "correction_candidate"),
        )
        self.conn.commit()
        payload = self._dcf_payload()
        apply_quote_applicable_rules_to_payload(payload)
        self.assertEqual(payload["items"][0]["usage"], "0.32码")
        self.assertFalse(payload["items"][0].get("correction_rule_applied"))

    def test_approved_rule_overrides_explicit_bom_and_recalculates(self) -> None:
        rid = self._insert_dcf_approved_rule()
        payload = self._dcf_payload()
        result = calculate_quote(payload)
        dcf_rows = [r for r in result.get("detail_rows") or [] if "DCF" in str(r.get("name") or "")]
        self.assertTrue(dcf_rows)
        row = dcf_rows[0]
        self.assertAlmostEqual(float(row.get("amount") or 0), 52.0, places=1)
        self.assertTrue(row.get("correction_rule_applied"))
        self.assertEqual(row.get("correction_rule_id"), rid)
        self.assertEqual(row.get("correction_rule_source"), "quote_correction_rules")
        self.assertEqual(row.get("correction_before_usage"), "0.32码")
        self.assertEqual(row.get("correction_before_unit_price"), "400元/码")
        self.assertEqual(row.get("correction_before_amount"), 128.0)
        self.assertTrue(str(row.get("correction_reason") or "").strip())

    def test_approved_rule_not_applied_when_size_mismatch(self) -> None:
        self._insert_dcf_approved_rule()
        payload = self._dcf_payload(product_size={"LCM": 40, "WCM": 30, "HCM": 20})
        apply_quote_applicable_rules_to_payload(payload)
        row = payload["items"][0]
        self.assertFalse(row.get("correction_rule_applied"))
        self.assertEqual(row.get("usage"), "0.32码")

    def test_approved_rule_not_applied_when_structure_mismatch(self) -> None:
        self._insert_dcf_approved_rule()
        payload = self._dcf_payload(structure_text="普通双肩包，无特殊结构")
        apply_quote_applicable_rules_to_payload(payload)
        row = payload["items"][0]
        self.assertFalse(row.get("correction_rule_applied"))
        self.assertEqual(row.get("usage"), "0.32码")

    def test_dcf_rule_requires_structure_and_size(self) -> None:
        rid = self._insert_dcf_approved_rule(f"{LEARNED_RULE_ID_PREFIX}dcf-match-test")
        row = self.conn.execute("SELECT * FROM quote_correction_rules WHERE rule_id = ?", (rid,)).fetchone()
        payload_row = dict(row)
        ctx_ok = {
            "product_name": "DCF收纳包",
            "product_type": "收纳包",
            "structure_text": "立体收纳包，无肩带",
            "product_size": {"LCM": 20},
            "material_name": "DCF外料",
            "material_spec": "DCF",
        }
        ctx_bad_size = {**ctx_ok, "product_size": {"LCM": 40}}
        ctx_bad_struct = {**ctx_ok, "structure_text": "普通双肩包"}
        self.assertTrue(rule_row_extended_match(payload_row, ctx_ok))
        self.assertFalse(rule_row_extended_match(payload_row, ctx_bad_size))
        self.assertFalse(rule_row_extended_match(payload_row, ctx_bad_struct))


if __name__ == "__main__":
    unittest.main()
