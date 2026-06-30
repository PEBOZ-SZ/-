from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import Mock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def sample_payload():
    return {
        "product_name": "测试包",
        "quantities": [500],
        "processing_fee": 10,
        "gross_margin_rate": 0.25,
        "include_fob": True,
        "items": [{"name": "PU料", "usage": "0.5平方", "unit_price": "6元", "amount": 3}],
    }


class GptQuoteActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.store_path = Path(self.tmpdir.name) / "quote_drafts.json"
        self.audit_path = Path(self.tmpdir.name) / "gpt_action_audit.jsonl"
        self.store_patch = patch("quote_draft_store.DRAFT_STORE_PATH", self.store_path)
        self.store_patch.start()

    def tearDown(self) -> None:
        self.store_patch.stop()
        self.tmpdir.cleanup()

    def test_gpt_quote_agent_token_wrong_returns_401(self) -> None:
        import server

        with patch.dict("os.environ", {"GPT_ACTION_TOKEN": "secret"}, clear=False):
            status, result = server.handle_gpt_quote_agent_request(
                {"session_id": "sess-gpt", "message": "数量改300", "payload": sample_payload()},
                "Bearer wrong",
            )

        self.assertEqual(status, 401)
        self.assertFalse(result["ok"])
        self.assertEqual(result["type"], "error")
        self.assertIsNone(result["draft"])
        self.assertIsNone(result["quote_result"])

    def test_gpt_quote_agent_token_missing_returns_401(self) -> None:
        import server

        with patch.dict("os.environ", {"GPT_ACTION_TOKEN": "secret"}, clear=False):
            status, result = server.handle_gpt_quote_agent_request(
                {"session_id": "sess-gpt", "message": "数量改300", "payload": sample_payload()},
                None,
            )

        self.assertEqual(status, 401)
        self.assertFalse(result["ok"])
        self.assertEqual(result["type"], "error")

    def test_gpt_quote_agent_token_correct_calls_same_agent_logic(self) -> None:
        import server

        calc = Mock(return_value={"ok": True, "result": {"quote_id": "calc-gpt", "tiers": [{"quantity": 300}]}})
        with patch.dict("os.environ", {"GPT_ACTION_TOKEN": "secret"}, clear=False), patch.object(
            server, "quote_calculate", calc
        ):
            status, result = server.handle_gpt_quote_agent_request(
                {"session_id": "sess-gpt-ok", "message": "数量改300", "payload": sample_payload()},
                "Bearer secret",
            )

        self.assertEqual(status, 200)
        self.assertEqual(result["type"], "quote_updated")
        self.assertEqual(result["draft"]["quantities"], [300])
        calc.assert_called_once()

    def test_gpt_quote_agent_rejects_empty_and_too_long_message(self) -> None:
        import server

        with patch.dict("os.environ", {"GPT_ACTION_TOKEN": "secret"}, clear=False):
            empty_status, empty_result = server.handle_gpt_quote_agent_request(
                {"session_id": "sess-empty", "message": "", "payload": sample_payload()},
                "Bearer secret",
            )
            long_status, long_result = server.handle_gpt_quote_agent_request(
                {"session_id": "sess-long", "message": "x" * 2001, "payload": sample_payload()},
                "Bearer secret",
            )

        self.assertEqual(empty_status, 400)
        self.assertEqual(empty_result["type"], "error")
        self.assertIsNone(empty_result["draft"])
        self.assertEqual(long_status, 400)
        self.assertEqual(long_result["type"], "error")

    def test_gpt_quote_agent_rejects_invalid_payload_shapes(self) -> None:
        import server

        with patch.dict("os.environ", {"GPT_ACTION_TOKEN": "secret"}, clear=False):
            status, result = server.handle_gpt_quote_agent_request(
                {"session_id": "sess-shape", "message": "数量改300", "payload": []},
                "Bearer secret",
            )

        self.assertEqual(status, 400)
        self.assertFalse(result["ok"])
        self.assertEqual(result["type"], "error")

    def test_gpt_quote_agent_http_endpoint_checks_token(self) -> None:
        import server

        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.QuoteHandler)
        setattr(httpd, "_quote_site", "front")
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{httpd.server_port}/gpt/quote-agent"
            body = json.dumps(
                {"session_id": "sess-http-bad", "message": "数量改300", "payload": sample_payload()},
                ensure_ascii=False,
            ).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=body,
                headers={"Content-Type": "application/json", "Authorization": "Bearer wrong"},
                method="POST",
            )
            with patch.dict("os.environ", {"GPT_ACTION_TOKEN": "secret"}, clear=False):
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(req, timeout=5)
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=5)

        self.assertEqual(raised.exception.code, 401)

    def test_gpt_quote_agent_http_rejects_non_object_json(self) -> None:
        import server

        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.QuoteHandler)
        setattr(httpd, "_quote_site", "front")
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{httpd.server_port}/gpt/quote-agent"
            req = urllib.request.Request(
                url,
                data=b"[]",
                headers={"Content-Type": "application/json", "Authorization": "Bearer secret"},
                method="POST",
            )
            with patch.dict("os.environ", {"GPT_ACTION_TOKEN": "secret"}, clear=False):
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(req, timeout=5)
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=5)

        self.assertEqual(raised.exception.code, 400)

    def test_gpt_quote_agent_writes_sanitized_audit_log(self) -> None:
        import server

        calc = Mock(
            return_value={
                "ok": True,
                "result": {
                    "quote_id": "calc-audit",
                    "detail_rows": [{"name": "PU料", "unit_price": 6.5}],
                    "tiers": [{"quantity": 300}],
                },
            }
        )
        with patch.dict("os.environ", {"GPT_ACTION_TOKEN": "secret"}, clear=False), patch.object(
            server, "quote_calculate", calc
        ), patch.object(server, "GPT_ACTION_AUDIT_PATH", self.audit_path):
            status, result = server.handle_gpt_quote_agent_request(
                {
                    "session_id": "sess-audit",
                    "message": "数量改300，PU料按6.5",
                    "payload": sample_payload(),
                    "quote_result": {
                        "quote_id": "secret-full-result",
                        "detail_rows": [{"name": "do-not-log"}],
                    },
                },
                "Bearer secret",
            )

        self.assertEqual(status, 200)
        self.assertEqual(result["type"], "quote_updated")
        records = [json.loads(line) for line in self.audit_path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["session_id"], "sess-audit")
        self.assertEqual(record["type"], "quote_updated")
        self.assertEqual(record["quote_id"], "calc-audit")
        self.assertFalse(record["saved"])
        raw_log = self.audit_path.read_text(encoding="utf-8")
        self.assertNotIn("detail_rows", raw_log)
        self.assertNotIn("do-not-log", raw_log)
        self.assertNotIn("Bearer", raw_log)
        self.assertNotIn("secret", raw_log)

    def test_gpt_quote_agent_normalizes_internal_error_body(self) -> None:
        import server

        internal = {
            "ok": False,
            "type": "error",
            "assistant_message": "internal failed",
            "draft": {"should": "not leak"},
            "quote_result": {"quote_id": "q-internal", "detail_rows": [{"name": "do-not-leak"}]},
            "missing_fields": ["x"],
            "risk_flags": ["y"],
        }
        with patch.dict("os.environ", {"GPT_ACTION_TOKEN": "secret"}, clear=False), patch.object(
            server, "handle_quote_agent_request", return_value=internal
        ), patch.object(server, "GPT_ACTION_AUDIT_PATH", self.audit_path):
            status, result = server.handle_gpt_quote_agent_request(
                {"session_id": "sess-error", "message": "重新计算", "payload": sample_payload()},
                "Bearer secret",
            )

        self.assertEqual(status, 200)
        self.assertFalse(result["ok"])
        self.assertEqual(result["type"], "error")
        self.assertEqual(result["assistant_message"], "internal failed")
        self.assertIsNone(result["draft"])
        self.assertIsNone(result["quote_result"])
        self.assertEqual(result["missing_fields"], [])
        self.assertEqual(result["risk_flags"], [])
        raw_log = self.audit_path.read_text(encoding="utf-8")
        self.assertNotIn("detail_rows", raw_log)
        self.assertNotIn("do-not-leak", raw_log)

    def test_unknown_gpt_path_requires_token_before_404(self) -> None:
        import server

        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.QuoteHandler)
        setattr(httpd, "_quote_site", "front")
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{httpd.server_port}/gpt/unknown"
            body = json.dumps({"session_id": "sess-unknown", "message": "test"}).encode("utf-8")

            missing_req = urllib.request.Request(
                url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            wrong_req = urllib.request.Request(
                url,
                data=body,
                headers={"Content-Type": "application/json", "Authorization": "Bearer wrong"},
                method="POST",
            )
            ok_req = urllib.request.Request(
                url,
                data=body,
                headers={"Content-Type": "application/json", "Authorization": "Bearer secret"},
                method="POST",
            )
            with patch.dict("os.environ", {"GPT_ACTION_TOKEN": "secret"}, clear=False), patch.object(
                server, "GPT_ACTION_AUDIT_PATH", self.audit_path
            ):
                with self.assertRaises(urllib.error.HTTPError) as missing:
                    urllib.request.urlopen(missing_req, timeout=5)
                with self.assertRaises(urllib.error.HTTPError) as wrong:
                    urllib.request.urlopen(wrong_req, timeout=5)
                with self.assertRaises(urllib.error.HTTPError) as ok:
                    urllib.request.urlopen(ok_req, timeout=5)
                ok_body = json.loads(ok.exception.read().decode("utf-8"))
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=5)

        self.assertEqual(missing.exception.code, 401)
        self.assertEqual(wrong.exception.code, 401)
        self.assertEqual(ok.exception.code, 404)
        self.assertFalse(ok_body["ok"])
        self.assertEqual(ok_body["type"], "error")
        self.assertIsNone(ok_body["draft"])
        self.assertIsNone(ok_body["quote_result"])
        raw_log = self.audit_path.read_text(encoding="utf-8")
        self.assertNotIn("Bearer", raw_log)
        self.assertNotIn("secret", raw_log)
        self.assertNotIn("detail_rows", raw_log)

    def test_gpt_quote_agent_route_does_not_expose_admin_export_or_approval_actions(self) -> None:
        schema = (PROJECT_ROOT / "docs" / "gpt_action_openapi.yaml").read_text(encoding="utf-8")

        self.assertIn("/gpt/quote-agent", schema)
        self.assertNotIn("/admin", schema)
        self.assertNotIn("quote_admin", schema)
        self.assertNotIn("quote_export", schema)
        self.assertNotIn("approve", schema.lower())
        self.assertNotIn("reject", schema.lower())

    def test_openapi_schema_declares_quote_agent_bearer_auth(self) -> None:
        schema = (PROJECT_ROOT / "docs" / "gpt_action_openapi.yaml").read_text(encoding="utf-8")

        self.assertIn("/gpt/quote-agent", schema)
        self.assertIn("operationId: quoteAgent", schema)
        self.assertIn("bearerAuth", schema)
        self.assertIn("securitySchemes", schema)


if __name__ == "__main__":
    unittest.main()
