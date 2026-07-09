from pathlib import Path


def test_quote_sheet_frontend_preserves_foreign_payee_fields() -> None:
    source = Path("static/quote_sheet.js").read_text(encoding="utf-8")

    assert "company_name_en" in source
    assert "account_type" in source
    assert "swift_code" in source
    assert "bank_address_en" in source
    assert "bank_note_en" in source
    assert "buildBankBlockPdfText" in source
    assert "payee," in source
    assert "selected_bank_account_type" in source


def test_quote_sheet_default_payee_picker_uses_cn_accounts_only() -> None:
    source = Path("static/quote_sheet.js").read_text(encoding="utf-8")

    assert 'DEFAULT_PAYEE_ACCOUNT_TYPE = "cn"' in source
    assert "accountType = currentPayeeAccountType()" in source
    assert 'accountType: "foreign"' in source


def test_quote_sheet_has_account_type_switcher_in_payee_section() -> None:
    html = Path("static/index.html").read_text(encoding="utf-8")
    css = Path("static/styles.css").read_text(encoding="utf-8")
    source = Path("static/quote_sheet.js").read_text(encoding="utf-8")

    assert 'id="qsPayeeTypeCn"' in html
    assert 'data-payee-account-type="cn"' in html
    assert "中国账户" in html
    assert 'id="qsPayeeTypeForeign"' in html
    assert 'data-payee-account-type="foreign"' in html
    assert "海外账户" in html
    assert ".qs-payee-type-toggle" in css
    assert "function setPayeeAccountType" in source
    assert "currentPayeeAccountType()" in source


def test_english_translation_does_not_force_foreign_payee_selection() -> None:
    source = Path("static/quote_sheet.js").read_text(encoding="utf-8")
    translate_start = source.index("async function requestTranslateEnglish")
    translate_end = source.index("async function ensureEnglishSnapshotReady")
    translate_body = source[translate_start:translate_end]

    assert "ensureForeignPayeeForEnglishExport" not in translate_body
