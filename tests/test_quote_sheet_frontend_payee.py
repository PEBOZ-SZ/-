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
