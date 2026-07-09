from pathlib import Path


def test_quote_sheet_has_frontend_english_label_fallbacks() -> None:
    source = Path("static/quote_sheet.js").read_text(encoding="utf-8")

    assert "EN_LABEL_FALLBACK" in source
    for text in (
        "Quotation",
        "Tel:",
        "Style Image",
        "Item",
        "Packaging",
        "Quote Date:",
        "Authorized Payee:",
        "Customer Signature:",
    ):
        assert text in source
    assert "labelsForLang" in source


def test_quote_sheet_english_issuer_uses_english_company_name() -> None:
    source = Path("static/quote_sheet.js").read_text(encoding="utf-8")

    assert "quoteIssuerCompanyNameForCurrentLang" in source
    assert "footerCompanyNameForCurrentLang" in source
    assert "default_company_name" in source


def test_quote_sheet_product_name_cells_wrap_without_letter_stacking() -> None:
    css = Path("static/styles.css").read_text(encoding="utf-8")

    assert ".qs-pdf-table tbody td.col-name" in css
    assert "overflow-wrap: break-word;" in css
    assert "word-break: normal;" in css
    assert ".qs-pdf-root[data-pdf-lang=\"en\"] .qs-pdf-table tbody td.col-name" in css
