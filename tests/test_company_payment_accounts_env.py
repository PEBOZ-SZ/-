import base64
import json


def test_company_payment_accounts_can_load_from_base64_env(monkeypatch):
    import company_payment_accounts as accounts

    payload = {
        "version": 1,
        "source": "env-test",
        "accounts": [
            {
                "company_name": "Env Payee Co",
                "bank_name": "Env Bank",
                "bank_account": "123456",
                "alipay": "pay@example.com",
            }
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    monkeypatch.setenv("COMPANY_PAYMENT_ACCOUNTS_JSON_B64", base64.b64encode(raw).decode("ascii"))

    listing = accounts.reload_company_payment_accounts()
    rows = accounts.list_company_payment_accounts()
    result = accounts.search_company_accounts("Env Payee Co")

    assert listing["source"] == "env-test"
    assert len(rows) >= 1
    assert result["ok"] is True
    assert result["exact"]["bank_account"] == "123456"


def test_peboz_usd_account_is_available_as_foreign_account(monkeypatch):
    import company_payment_accounts as accounts
    from quote_sheet_i18n import format_usd_bank_block_en

    payload = {
        "version": 1,
        "source": "env-without-peboz-usd",
        "accounts": [
            {
                "company_name": "Domestic Payee Co",
                "bank_name": "Domestic Bank",
                "bank_account": "123456",
            }
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    monkeypatch.setenv("COMPANY_PAYMENT_ACCOUNTS_JSON_B64", base64.b64encode(raw).decode("ascii"))

    accounts.reload_company_payment_accounts()
    foreign = accounts.search_company_accounts(
        "SHENZHEN PEBOZ PRODUCTS LIMITED",
        account_type=accounts.ACCOUNT_TYPE_FOREIGN,
    )
    cn = accounts.search_company_accounts("", account_type=accounts.ACCOUNT_TYPE_CN, limit=20)

    assert foreign["ok"] is True
    assert foreign["exact"]["account_type"] == accounts.ACCOUNT_TYPE_FOREIGN
    assert foreign["exact"]["currency"] == "USD"
    assert foreign["exact"]["bank_account"] == "7419 7587 9516"
    assert foreign["exact"]["swift_code"] == "BKCHCNBJ45A"
    assert all(
        row["company_name"] != "SHENZHEN PEBOZ PRODUCTS LIMITED"
        for row in cn["candidates"]
    )

    block = format_usd_bank_block_en(foreign["exact"])
    assert "Bank Information:" in block
    assert "NAME: SHENZHEN PEBOZ PRODUCTS LIMITED" in block
    assert "A/C: 7419 7587 9516" in block
    assert "BANK NAME: BANK OF CHINA, BAOAN SUB-BRANCH, SHENZHEN" in block
    assert "SWIFT CODE: BKCHCNBJ45A" in block
    assert "ADD: 1/F BLOCK 1, WANJUN COMMERCLAL BLDG" in block
    assert "all remitter bank charges are on buyer's account" in block
