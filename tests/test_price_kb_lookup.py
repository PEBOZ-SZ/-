from __future__ import annotations


def _entry(name: str, spec: str, price: str):
    import re

    from price_kb import KBEntry, _tokens_from_text
    match = re.search(r"\d+(?:\.\d+)?", price)

    return KBEntry(
        raw_name=name,
        raw_spec=spec,
        raw_price=price,
        auto_learned=False,
        normalised_name=name,
        name_tokens=frozenset(_tokens_from_text(f"{name} {spec}")),
        unit_price_value=float(match.group(0)) if match else 0.0,
        unit_price_unit="",
        price_note="",
    )


def test_600d_oxford_fabric_beats_accessory_with_same_numeric_token():
    from price_kb import PriceKB

    kb = PriceKB(
        [
            _entry("4分600D平口", "", "0.25"),
            _entry("600D牛津布", "140*90CM", "14元/码²"),
            _entry("600D涤纶牛津布", "140*90CM", "16.7439元/㎡"),
        ]
    )

    hit = kb.lookup("600D牛津布", "600D", min_score=0.1)

    assert hit is not None
    assert hit.entry.raw_name == "600D牛津布"


def test_chinese_material_words_are_tokenized_for_lookup():
    from price_kb import _tokens_from_text

    tokens = _tokens_from_text("600D牛津布")

    assert "600" in tokens
    assert "牛津布" in tokens
    assert "牛津" in tokens
