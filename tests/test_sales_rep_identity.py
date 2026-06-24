"""非企微业务员身份识别与绑定。"""

from __future__ import annotations

import unittest

from sales_rep_fields import (
    build_sales_identity,
    extract_sales_fields,
    identity_from_quote_params,
    is_valid_local_sales_user_id,
    normalize_sales_rep,
    resolve_local_sales_identity,
)


class NormalizeSalesRepTest(unittest.TestCase):
    def test_code_and_name(self) -> None:
        out = normalize_sales_rep("20 刘璇")
        self.assertEqual(out["sales_user_id"], "local:20")
        self.assertEqual(out["sales_user_code"], "20")
        self.assertEqual(out["sales_user_name"], "刘璇")
        self.assertEqual(out["sales_user_label"], "20-刘璇")
        self.assertEqual(out["identity_source"], "sheet")

    def test_dash_and_colon_variants(self) -> None:
        for raw in ("20-刘璇", "20_刘璇", "20：刘璇"):
            out = normalize_sales_rep(raw)
            self.assertEqual(out["sales_user_id"], "local:20")
            self.assertEqual(out["sales_user_name"], "刘璇")

    def test_code_only(self) -> None:
        out = normalize_sales_rep("08")
        self.assertEqual(out["sales_user_id"], "local:08")
        self.assertEqual(out["sales_user_name"], "08")

    def test_name_only(self) -> None:
        out = normalize_sales_rep("刘璇")
        self.assertEqual(out["sales_user_id"], "local:name:刘璇")
        self.assertEqual(out["sales_user_name"], "刘璇")

    def test_another_pair(self) -> None:
        out = normalize_sales_rep("21 肖子贞")
        self.assertEqual(out["sales_user_id"], "local:21")
        self.assertEqual(out["sales_user_name"], "肖子贞")


class ExtractSalesFieldsTest(unittest.TestCase):
    def _assert_pair(self, quote_params: dict, *, code: str, name: str) -> None:
        fields = extract_sales_fields(quote_params)
        self.assertEqual(fields["sales_code"], code)
        self.assertEqual(fields["sales_name"], name)
        ident = identity_from_quote_params(quote_params)
        if code and name:
            self.assertEqual(ident["sales_user_id"], f"local:{code}")
            self.assertEqual(ident["sales_user_name"], name)
            self.assertEqual(ident["sales_user_label"], f"{code}-{name}")
        elif name and not code:
            self.assertEqual(ident["sales_user_id"], f"local:name:{name}")
            self.assertEqual(ident["sales_user_name"], name)

    def test_sales_rep_field_combined_space(self) -> None:
        self._assert_pair({"A": {"业务员": "20 刘璇"}}, code="20", name="刘璇")

    def test_sales_rep_field_combined_dash(self) -> None:
        self._assert_pair({"A": {"业务员": "20-刘璇"}}, code="20", name="刘璇")

    def test_sales_rep_field_name_only(self) -> None:
        self._assert_pair({"A": {"业务员": "刘璇"}}, code="", name="刘璇")

    def test_separate_code_and_name_fields(self) -> None:
        self._assert_pair(
            {"A": {"业务员编号": "20", "业务员姓名": "刘璇"}},
            code="20",
            name="刘璇",
        )


class SheetIdentityTest(unittest.TestCase):
    def test_extract_from_section_a(self) -> None:
        quote_params = {
            "A": {
                "业务员编号": "20 刘璇",
                "客户名称": "某客户",
                "国家": "美国",
            }
        }
        ident = identity_from_quote_params(quote_params)
        self.assertEqual(ident["sales_user_id"], "local:20")
        self.assertEqual(ident["sales_user_name"], "刘璇")
        fields = extract_sales_fields(quote_params)
        self.assertEqual(fields["sales_code"], "20")
        self.assertEqual(fields["sales_name"], "刘璇")

    def test_resolve_prefers_payload_manual_over_cookie(self) -> None:
        cookie = "aq_sales_user_id=local:99; aq_sales_user_name=old"
        payload = {"sales_rep_input": "20 刘璇"}
        ident = resolve_local_sales_identity(cookie, payload)
        self.assertEqual(ident["sales_user_id"], "local:20")
        self.assertEqual(ident["identity_source"], "manual")

    def test_resolve_cookie_fallback(self) -> None:
        cookie = "aq_sales_user_id=local:21; aq_sales_user_name=%E8%82%96%E5%AD%90%E8%B4%9E"
        ident = resolve_local_sales_identity(cookie)
        self.assertEqual(ident["sales_user_id"], "local:21")
        self.assertEqual(ident["sales_user_name"], "肖子贞")
        self.assertEqual(ident["identity_source"], "browser")

    def test_invalid_uuid_cookie_ignored(self) -> None:
        cookie = "aq_sales_user_id=abc123def4567890"
        ident = resolve_local_sales_identity(cookie)
        self.assertEqual(ident, {})

    def test_valid_local_id(self) -> None:
        self.assertTrue(is_valid_local_sales_user_id("local:20"))
        self.assertTrue(is_valid_local_sales_user_id("local:name:刘璇"))
        self.assertFalse(is_valid_local_sales_user_id("wecom:alice"))
        self.assertFalse(is_valid_local_sales_user_id("abc123"))


if __name__ == "__main__":
    unittest.main()
