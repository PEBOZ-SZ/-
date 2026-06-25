from __future__ import annotations

import json

from mcp_server.tools.quote_calculate import quote_calculate
from mcp_server.tools.price_lookup import price_lookup
from mcp_server.tools.quote_qa import quote_qa
from mcp_server.tools.quote_explain import quote_explain
from mcp_server.tools.quote_patch_preview import quote_patch_preview


def _sample_input(role: str = "sales", include_items: bool = True) -> dict:
    payload = {
        "product_name": "测试背包",
        "quantities": [300, 500, 1000],
        "mold_fee": 1000,
        "processing_fee": 12,
        "system_overhead": 4,
        "gross_margin_rate": 0.35,
        "include_fob": True,
    }
    if include_items:
        payload["items"] = [
            {
                "name": "测试面料",
                "spec": "600D",
                "usage": "1码²",
                "unit_price": "10元/码²",
                "amount": 10,
            }
        ]

    return {
        "user_context": {
            "user_id": "sales_001",
            "user_name": "张三",
            "role": role,
            "session_id": "sess_001",
        },
        "payload": payload,
    }


def _price_lookup_sample(role: str = "sales", query: dict | None = None) -> dict:
    return {
        "user_context": {
            "user_id": "sales_001",
            "user_name": "张三",
            "role": role,
            "session_id": "sess_001",
        },
        "query": query if query is not None else {"name": "拉链", "spec": "", "limit": 5},
    }


def _quote_qa_sample(role: str = "sales", query: dict | None = None) -> dict:
    return {
        "user_context": {
            "user_id": "sales_001",
            "user_name": "张三",
            "role": role,
            "session_id": "sess_001",
        },
        "query": query if query is not None else {"user_text": "客户嫌这个包贵，怎么解释？"},
    }


def _quote_explain_quote_result() -> dict:
    return {
        "product_name": "测试背包",
        "material_total": 100,
        "material_total_text": "100元",
        "tiers": [
            {
                "quantity": 300,
                "cost_before_margin": 55.2,
                "exw_price": 84.9,
                "fob_price": 88.9,
                "margin_rate": 0.35,
            },
            {
                "quantity": 1000,
                "cost_before_margin": 48.6,
                "exw_price": 74.8,
                "fob_price": 78.8,
                "margin_rate": 0.35,
            },
        ],
        "items": [],
        "warnings": [],
        "review_required": False,
    }


def _quote_explain_sample(role: str = "sales", query: dict | None = None) -> dict:
    return {
        "user_context": {
            "user_id": "sales_001",
            "user_name": "张三",
            "role": role,
            "session_id": "sess_001",
        },
        "query": query
        if query is not None
        else {
            "user_question": "为什么 300 件比 1000 件贵？",
            "quote_result": _quote_explain_quote_result(),
            "audience": "sales_internal",
        },
    }


def _quote_patch_preview_sample(role: str = "sales", query: dict | None = None) -> dict:
    return {
        "user_context": {
            "user_id": "sales_001",
            "user_name": "张三",
            "role": role,
            "session_id": "sess_001",
        },
        "query": query
        if query is not None
        else {
            "quote_result": _quote_explain_quote_result(),
            "patch": {"quantity": 1000},
        },
    }


def _run_case(
    label: str,
    tool_func,
    sample: dict,
    expected_ok: bool,
    error_contains: str | None = None,
    require_answer: bool = False,
) -> bool:
    result = tool_func(sample)
    ok_matches = result.get("ok") is expected_ok
    error_matches = True
    if error_contains:
        error_matches = error_contains in str(result.get("error", ""))
    answer_matches = True
    if require_answer:
        answer_matches = bool((result.get("result") or {}).get("answer"))

    passed = ok_matches and error_matches and answer_matches
    status = "PASS" if passed else "FAIL"
    print(f"[MCP self-check] {label}: {status} ok={str(result.get('ok')).lower()}")
    if not passed:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return passed


def main() -> None:
    print("[MCP self-check] run from project root:")
    print("cd D:/完整版自动报价/自报项目")
    print("python -m mcp_server.server")

    checks = [
        _run_case("sales quote_calculate", quote_calculate, _sample_input(role="sales"), True),
        _run_case("admin quote_calculate", quote_calculate, _sample_input(role="admin"), True),
        _run_case(
            "guest forbidden",
            quote_calculate,
            _sample_input(role="guest"),
            False,
            "无权调用 quote_calculate",
        ),
        _run_case(
            "missing items",
            quote_calculate,
            _sample_input(role="sales", include_items=False),
            False,
            "缺少明细 items",
        ),
        _run_case(
            "sales price_lookup",
            price_lookup,
            _price_lookup_sample(role="sales"),
            True,
        ),
        _run_case(
            "guest price_lookup forbidden",
            price_lookup,
            _price_lookup_sample(role="guest"),
            False,
            "无权调用 price_lookup",
        ),
        _run_case(
            "price_lookup missing name",
            price_lookup,
            _price_lookup_sample(role="sales", query={}),
            False,
            "name",
        ),
        _run_case(
            "sales quote_qa",
            quote_qa,
            _quote_qa_sample(role="sales"),
            True,
            require_answer=True,
        ),
        _run_case(
            "guest quote_qa forbidden",
            quote_qa,
            _quote_qa_sample(role="guest", query={"user_text": "600D牛津布是什么？"}),
            False,
            "无权调用 quote_qa",
        ),
        _run_case(
            "quote_qa missing user_text",
            quote_qa,
            _quote_qa_sample(role="sales", query={}),
            False,
            "user_text",
        ),
        _run_case(
            "quote_qa blocked write/quote intent",
            quote_qa,
            _quote_qa_sample(role="sales", query={"user_text": "帮我重新报价并保存"}),
            False,
            "只读",
        ),
        _run_case(
            "sales quote_explain",
            quote_explain,
            _quote_explain_sample(role="sales"),
            True,
            require_answer=True,
        ),
        _run_case(
            "guest quote_explain forbidden",
            quote_explain,
            _quote_explain_sample(role="guest"),
            False,
            "无权调用 quote_explain",
        ),
        _run_case(
            "quote_explain missing quote_result",
            quote_explain,
            _quote_explain_sample(role="sales", query={"user_question": "这个报价为什么贵？"}),
            False,
            "quote_result",
        ),
        _run_case(
            "quote_explain blocked write/quote intent",
            quote_explain,
            _quote_explain_sample(
                role="sales",
                query={
                    "user_question": "帮我重新报价并保存",
                    "quote_result": _quote_explain_quote_result(),
                },
            ),
            False,
            "只解释",
        ),
        _run_case(
            "quote_patch_preview",
            quote_patch_preview,
            _quote_patch_preview_sample(role="sales"),
            True,
        ),
    ]
    if all(checks):
        print("[MCP self-check] all checks passed")
    else:
        print("[MCP self-check] some checks failed")


if __name__ == "__main__":
    main()
