from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class QuoteDraftStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.store_path = Path(self.tmpdir.name) / "quote_drafts.json"
        self.patch_path = patch("quote_draft_store.DRAFT_STORE_PATH", self.store_path)
        try:
            self.patch_path.start()
        except ModuleNotFoundError:
            self.patch_path.stop()
            raise

    def tearDown(self) -> None:
        self.patch_path.stop()
        self.tmpdir.cleanup()

    def test_create_quote_draft_from_quote_result(self) -> None:
        from quote_draft_store import create_quote_draft, get_quote_draft

        quote_result = {
            "product_name": "测试包",
            "settings": {
                "processing_fee": 12,
                "gross_margin_rate": 0.35,
                "include_fob": True,
            },
            "tiers": [{"quantity": 300}],
            "detail_rows": [
                {"name": "PU料", "usage": "0.5平方", "unit_price": "6元", "amount": 3},
            ],
            "validation_errors": ["材料缺片数"],
        }

        draft = create_quote_draft("sess-1", quote_result=quote_result)

        self.assertEqual(draft["session_id"], "sess-1")
        self.assertEqual(draft["product_name"], "测试包")
        self.assertEqual(draft["quantities"], [300])
        self.assertEqual(draft["processing_fee"], 12)
        self.assertEqual(draft["gross_margin_rate"], 0.35)
        self.assertTrue(draft["include_fob"])
        self.assertEqual(draft["items"][0]["name"], "PU料")
        self.assertEqual(draft["missing_fields"], ["材料缺片数"])
        self.assertEqual(get_quote_draft("sess-1")["draft_id"], draft["draft_id"])

    def test_update_quote_draft_applies_structured_patches(self) -> None:
        from quote_draft_store import create_quote_draft, update_quote_draft

        create_quote_draft(
            "sess-2",
            source_payload={
                "product_name": "测试包",
                "quantities": [500],
                "processing_fee": 10,
                "gross_margin_rate": 0.25,
                "items": [{"name": "PU料", "usage": "0.5", "unit_price": "6", "amount": 3}],
            },
        )

        draft = update_quote_draft(
            "sess-2",
            [
                {"op": "set_quantities", "quantities": [300]},
                {"op": "set_margin", "gross_margin_rate": 0.30},
                {"op": "set_processing_fee", "processing_fee": 15},
                {"op": "set_material_price", "material": "PU料", "unit_price": 6.5},
                {"op": "set_material_usage", "material": "PU料", "usage": 0.56},
            ],
        )

        self.assertEqual(draft["quantities"], [300])
        self.assertEqual(draft["gross_margin_rate"], 0.30)
        self.assertEqual(draft["processing_fee"], 15)
        self.assertEqual(draft["items"][0]["unit_price"], 6.5)
        self.assertEqual(draft["items"][0]["usage"], 0.56)


if __name__ == "__main__":
    unittest.main()
