"""纠错候选归因与候选池。"""

from __future__ import annotations

import sqlite3
import unittest

from quote_correction_candidate_pool import (
    CANDIDATE_STATUS_PENDING,
    CANDIDATE_STATUS_REJECTED,
    classify_correction_error,
    capture_correction_candidates_from_bom_save,
    insert_correction_candidate,
    list_correction_candidates,
    reject_correction_candidate,
    size_matches_condition,
)
from quote_correction_learning import init_correction_learning_storage, set_test_connection


class CorrectionLearningDbTest(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        set_test_connection(self.conn)
        init_correction_learning_storage()

    def tearDown(self) -> None:
        set_test_connection(None)
        self.conn.close()


class ClassifyCorrectionErrorTest(unittest.TestCase):
    def test_usage_overestimated(self) -> None:
        out = classify_correction_error(
            {"name": "DCF外料", "usage": "0.32码", "unit_price": "24.5/码", "amount": 7.84},
            {"name": "DCF外料", "usage": "0.13码", "unit_price": "24.5/码", "amount": 3.19},
            {"product_name": "立体收纳包", "product_type": "收纳包"},
        )
        self.assertEqual(out["error_type"], "usage_overestimated")

    def test_usage_underestimated(self) -> None:
        out = classify_correction_error(
            {"name": "DCF外料", "usage": "0.13码", "unit_price": "24.5/码"},
            {"name": "DCF外料", "usage": "0.32码", "unit_price": "24.5/码"},
            {},
        )
        self.assertEqual(out["error_type"], "usage_underestimated")

    def test_unit_price_wrong(self) -> None:
        out = classify_correction_error(
            {"name": "里布", "usage": "0.8码", "unit_price": "12/码"},
            {"name": "里布", "usage": "0.8码", "unit_price": "18/码"},
            {},
        )
        self.assertEqual(out["error_type"], "unit_price_wrong")

    def test_unit_mismatch(self) -> None:
        out = classify_correction_error(
            {"name": "PU拉牌", "usage": "1码", "unit_price": "24.5/码"},
            {"name": "PU拉牌", "usage": "1码", "unit_price": "2/个"},
            {},
        )
        self.assertEqual(out["error_type"], "unit_mismatch")

    def test_missing_material(self) -> None:
        out = classify_correction_error(
            {},
            {"name": "新拉链", "usage": "1条", "unit_price": "3/条", "amount": 3},
            {},
        )
        self.assertEqual(out["error_type"], "missing_material")

    def test_extra_material(self) -> None:
        out = classify_correction_error(
            {"name": "织带", "usage": "1.2米", "unit_price": "2/米", "amount": 2.4},
            {"name": "织带", "usage": "-", "unit_price": "-", "amount": 0},
            {},
        )
        self.assertEqual(out["error_type"], "extra_material")


class CandidatePoolTest(CorrectionLearningDbTest):
    def test_first_correction_creates_pending_candidate(self) -> None:
        cids = capture_correction_candidates_from_bom_save(
            "q-test-1",
            old_items=[{"name": "DCF外料", "usage": "0.32码", "unit_price": "24.5/码", "amount": 7.84}],
            new_items=[{"name": "DCF外料", "usage": "0.13码", "unit_price": "24.5/码", "amount": 3.19}],
            quote={"product_name": "立体收纳包", "product_type": "收纳包", "quote_id": "B001"},
            corrected_by="admin",
        )
        self.assertTrue(cids)
        pending = list_correction_candidates(status=CANDIDATE_STATUS_PENDING)
        self.assertGreaterEqual(len(pending), 1)
        self.assertEqual(pending[0]["status"], CANDIDATE_STATUS_PENDING)

    def test_rejected_candidate_stays_rejected(self) -> None:
        cid = insert_correction_candidate(
            quote_uid="q-x",
            material_name="测试",
            system_usage="1码",
            corrected_usage="0.5码",
            error_type="usage_overestimated",
            reason="test",
        )
        reject_correction_candidate(cid, review_note="不适用")
        items = list_correction_candidates(status=CANDIDATE_STATUS_REJECTED)
        self.assertTrue(any(i["candidate_id"] == cid for i in items))

    def test_size_condition(self) -> None:
        self.assertTrue(size_matches_condition({"LCM": 20, "WCM": 15, "HCM": 10}, {"max_l_cm": 25}))
        self.assertFalse(size_matches_condition({"LCM": 30, "WCM": 15, "HCM": 10}, {"max_l_cm": 25}))


if __name__ == "__main__":
    unittest.main()
