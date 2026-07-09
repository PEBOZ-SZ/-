import re
from pathlib import Path


def test_pdf_signature_area_is_lower_than_payment_lines() -> None:
    css = Path("static/styles.css").read_text(encoding="utf-8")

    root_match = re.search(r"\.qs-pdf-root\s*\{(?P<body>[^}]+)\}", css)
    assert root_match is not None
    assert "--qs-pdf-signature-offset: 64mm;" in root_match.group("body")

    stamp_match = re.search(r"\.qs-pdf-stamp-side\s*\{(?P<body>[^}]+)\}", css)
    assert stamp_match is not None
    stamp_body = stamp_match.group("body")
    assert "margin-top: var(--qs-pdf-signature-offset);" in stamp_body

    pay_inner_match = re.search(r"\.qs-pdf-pay-inner\s*\{(?P<body>[^}]+)\}", css)
    assert pay_inner_match is not None
    assert "top: 0;" in pay_inner_match.group("body")


def test_english_signature_area_uses_lower_signature_offset() -> None:
    css = Path("static/styles.css").read_text(encoding="utf-8")

    english_stamp_match = re.search(
        r'\.qs-pdf-root\[data-pdf-lang="en"\]\s+\.qs-pdf-stamp-side\s*\{(?P<body>[^}]+)\}',
        css,
    )
    assert english_stamp_match is not None
    assert "margin-top: var(--qs-pdf-signature-offset);" in english_stamp_match.group("body")
    assert "margin-top: 18px;" not in english_stamp_match.group("body")

    english_customer_match = re.search(
        r'\.qs-pdf-root\[data-pdf-lang="en"\]\s+\.qs-pdf-cust-sign-side\s*\{(?P<body>[^}]+)\}',
        css,
    )
    assert english_customer_match is not None
    assert "calc(var(--qs-pdf-signature-offset) + 29mm)" in english_customer_match.group("body")
