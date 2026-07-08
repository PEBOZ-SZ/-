from quote_sheet_direct_prefill import build_direct_quote_sheet_prefill_payload


def test_direct_prefill_collapses_material_items_into_one_customer_product_row():
    payload = build_direct_quote_sheet_prefill_payload(
        {
            "product_name": "午餐包",
            "size": "30×20×10cm",
            "description": "600D牛津布，PEVA内里，EPE保温棉",
            "packaging": "1个/OPP袋",
            "quantity": 500,
            "unit_price": 18.6,
            "amount": 9300,
            "items": [
                {"name": "600D牛津布", "usage": "0.5码", "amount": 4.5},
                {"name": "拉链", "usage": "1条", "amount": 0.8},
                {"name": "刀模费", "remark": "刀模摊销1000元", "amount": 1000},
            ],
        }
    )

    assert len(payload["rows"]) == 1
    row = payload["rows"][0]
    assert row["name"] == "午餐包"
    assert row["size"] == "30×20×10cm"
    assert row["desc"] == "600D牛津布，PEVA内里，EPE保温棉"
    assert row["pack"] == "1个/OPP袋"
    assert row["qty"] == "500"
    assert row["price"] == "18.6"
    assert row["total"] == "9300"
    assert row["note"] == ""


def test_direct_prefill_uses_first_quote_sheet_row_and_drops_internal_remark():
    payload = build_direct_quote_sheet_prefill_payload(
        {
            "quote_sheet_rows": [
                {
                    "product_name": "收纳包",
                    "size": "45×30×17cm",
                    "description": "牛津布收纳包",
                    "packaging": "1个/胶袋",
                    "quantity": 300,
                    "unit_price": 22,
                    "amount": 6600,
                    "remark": "刀模费已摊销，AI暂估待确认",
                },
                {
                    "product_name": "第二档数量",
                    "quantity": 500,
                    "unit_price": 20,
                    "amount": 10000,
                },
            ]
        }
    )

    assert len(payload["rows"]) == 1
    row = payload["rows"][0]
    assert row["name"] == "收纳包"
    assert row["qty"] == "300"
    assert row["price"] == "22"
    assert row["note"] == ""


def test_direct_prefill_reads_nested_quote_result_payload():
    payload = build_direct_quote_sheet_prefill_payload(
        {
            "quote_result": {
                "product_name": "化妆包",
                "product_size": {"length_cm": 20, "width_cm": 10, "height_cm": 8},
                "packaging": "1个/OPP袋",
                "customer_description": "PU面料，拉链开口",
                "tiers": [{"quantity": 1000, "exw_price": 9.8, "amount": 9800}],
                "items": [{"name": "PU料", "amount": 2.5}],
            }
        }
    )

    assert len(payload["rows"]) == 1
    row = payload["rows"][0]
    assert row["name"] == "化妆包"
    assert row["size"] == "20×10×8cm"
    assert row["pack"] == "1个/OPP袋"
    assert row["desc"] == "PU面料，拉链开口"
    assert row["qty"] == "1000"
    assert row["price"] == "9.8"
    assert row["total"] == "9800"


def test_direct_prefill_reads_chinese_quote_sheet_field_names():
    payload = build_direct_quote_sheet_prefill_payload(
        {
            "产品名称": "篮球包",
            "尺寸": "32×19×45cm",
            "描述": "篮球背包；600D防泼水",
            "包装": "单个OPP袋，纸箱包装",
            "报价汇总": [
                {
                    "数量": 500,
                    "EXW单价": 76.1,
                    "总价": 38050,
                    "备注": "500个；刀模费1000元按500个摊销。",
                },
                {"数量": 1000, "EXW单价": 73, "总价": 73000},
            ],
        }
    )

    assert len(payload["rows"]) == 1
    row = payload["rows"][0]
    assert row["name"] == "篮球包"
    assert row["size"] == "32×19×45cm"
    assert row["desc"] == "篮球背包；600D防泼水"
    assert row["pack"] == "单个OPP袋，纸箱包装"
    assert row["qty"] == "500"
    assert row["price"] == "76.1"
    assert row["total"] == "38050"
    assert row["note"] == ""
