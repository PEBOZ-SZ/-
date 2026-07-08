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
    assert len(rows) == 1
    assert result["ok"] is True
    assert result["exact"]["bank_account"] == "123456"
