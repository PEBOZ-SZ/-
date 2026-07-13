from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class QuoteImportApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    @contextmanager
    def _storage(self):
        import quote_upload_storage as storage

        old_db_path = storage.DB_PATH
        old_data_dir = storage.DATA_DIR
        old_uploads_dir = storage.UPLOADS_DIR
        root = Path(self.tmpdir.name)
        storage.DATA_DIR = root
        storage.UPLOADS_DIR = root / "uploads"
        storage.DB_PATH = root / "quotes.db"
        try:
            yield storage
        finally:
            storage.DB_PATH = old_db_path
            storage.DATA_DIR = old_data_dir
            storage.UPLOADS_DIR = old_uploads_dir

    def _payload(self, quote_no: str = "B260160", price: float = 68.1) -> dict:
        return {
            "quote_no": quote_no,
            "salesperson": "08",
            "customer_name": "1688-Yvy",
            "customer_country": "中国",
            "currency_unit": "RMB/个",
            "products": [
                {
                    "name": "PU女包",
                    "size": "35.56×19.05×22.85cm",
                    "desc": "主料：PU荔纹外料，米色",
                    "pack": "1个/胶袋",
                    "qty": 1000,
                    "price": price,
                    "total": 1000 * price,
                    "note": "暂估报价，需业务员确认",
                }
            ],
            "materials": [
                {
                    "name": "PU荔纹外料",
                    "spec": "标准厚度，米色",
                    "usage": 0.5,
                    "unit": "码",
                    "unit_price": 14.5,
                    "amount": 7.3,
                    "remark": "知识库价",
                }
            ],
            "source_file_name": "01-B260160.xlsx",
        }

    def test_import_payload_saves_quote_sheet_rows_for_existing_prefill(self) -> None:
        from quote_import_store import import_quote_payload
        from quote_sheet_prefill import build_quote_sheet_prefill_payload

        with self._storage():
            result = import_quote_payload(
                self._payload(),
                sales_user_id="sales-08",
                sales_user_name="08",
            )
            prefill = build_quote_sheet_prefill_payload("B260160", "sales-08")

        self.assertTrue(result["success"])
        self.assertEqual(result["quote_no"], "B260160")
        self.assertEqual(result["quote_uid"], "B260160")
        self.assertIn("view=quoteSheet", result["preview_url"])
        self.assertIn("view=quoteSheet", result["download_url"])
        self.assertIn("exportMode=pdf_rmb", result["download_url"])
        self.assertIsNotNone(prefill)
        row = prefill["rows"][0]
        self.assertEqual(row["name"], "PU女包")
        self.assertEqual(row["size"], "35.56×19.05×22.85cm")
        self.assertEqual(row["desc"], "主料：PU荔纹外料，米色")
        self.assertEqual(row["pack"], "1个/胶袋")
        self.assertEqual(row["qty"], "1000")
        self.assertEqual(row["price"], "68.1")
        self.assertEqual(row["total"], "68100")
        self.assertEqual(row["note"], "暂估报价，需业务员确认")
        self.assertEqual(prefill["meta"]["quote_no"], "B260160")
        self.assertEqual(prefill["meta"]["cust_name"], "1688-Yvy")

    def test_duplicate_quote_no_creates_next_version_under_same_quote_uid(self) -> None:
        from quote_import_store import import_quote_payload

        with self._storage():
            first = import_quote_payload(
                self._payload(price=68.1),
                sales_user_id="sales-08",
                sales_user_name="08",
            )
            second = import_quote_payload(
                self._payload(price=70.5),
                sales_user_id="sales-08",
                sales_user_name="08",
            )

        self.assertTrue(first["success"])
        self.assertTrue(second["success"])
        self.assertEqual(first["quote_uid"], "B260160")
        self.assertEqual(second["quote_uid"], "B260160")
        self.assertEqual(first["version_no"], 1)
        self.assertEqual(second["version_no"], 2)

    def test_import_payload_requires_quote_no_and_product_row(self) -> None:
        from quote_import_store import import_quote_payload

        with self._storage():
            with self.assertRaises(ValueError) as missing_quote:
                import_quote_payload({"products": [{"name": "包"}]}, sales_user_id="sales-08")
            with self.assertRaises(ValueError) as missing_rows:
                import_quote_payload({"quote_no": "B260161", "products": []}, sales_user_id="sales-08")

        self.assertIn("quote_no", str(missing_quote.exception))
        self.assertIn("产品行", str(missing_rows.exception))

    def test_http_import_accepts_gpt_bearer_token(self) -> None:
        import server

        with self._storage(), patch.dict("os.environ", {"GPT_ACTION_TOKEN": "secret"}, clear=False):
            httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.QuoteHandler)
            setattr(httpd, "_quote_site", "front")
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            try:
                url = f"http://127.0.0.1:{httpd.server_port}/api/quote/import"
                req = urllib.request.Request(
                    url,
                    data=json.dumps(self._payload(), ensure_ascii=False).encode("utf-8"),
                    headers={"Content-Type": "application/json", "Authorization": "Bearer secret"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
            finally:
                httpd.shutdown()
                httpd.server_close()
                thread.join(timeout=5)

        self.assertTrue(body["success"])
        self.assertEqual(body["quote_no"], "B260160")
        self.assertEqual(body["quote_uid"], "B260160")
        self.assertTrue(body["preview_url"].startswith(f"http://127.0.0.1:{httpd.server_port}/"))
        self.assertTrue(body["download_url"].startswith(f"http://127.0.0.1:{httpd.server_port}/"))
        self.assertIn("view=quoteSheet", body["download_url"])
        self.assertIn("exportMode=pdf_rmb", body["download_url"])

    def test_http_import_rejects_wrong_gpt_token(self) -> None:
        import server

        with self._storage(), patch.dict("os.environ", {"GPT_ACTION_TOKEN": "secret"}, clear=False):
            httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.QuoteHandler)
            setattr(httpd, "_quote_site", "front")
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            try:
                url = f"http://127.0.0.1:{httpd.server_port}/api/quote/import"
                req = urllib.request.Request(
                    url,
                    data=json.dumps(self._payload(), ensure_ascii=False).encode("utf-8"),
                    headers={"Content-Type": "application/json", "Authorization": "Bearer wrong"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(req, timeout=5)
            finally:
                httpd.shutdown()
                httpd.server_close()
                thread.join(timeout=5)

        self.assertEqual(raised.exception.code, 401)


if __name__ == "__main__":
    unittest.main()
