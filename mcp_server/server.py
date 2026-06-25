from __future__ import annotations

import json

from mcp_server.tools.quote_calculate import quote_calculate


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


def _run_case(label: str, sample: dict, expected_ok: bool, error_contains: str | None = None) -> bool:
    result = quote_calculate(sample)
    ok_matches = result.get("ok") is expected_ok
    error_matches = True
    if error_contains:
        error_matches = error_contains in str(result.get("error", ""))

    passed = ok_matches and error_matches
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
        _run_case("sales quote_calculate", _sample_input(role="sales"), True),
        _run_case("admin quote_calculate", _sample_input(role="admin"), True),
        _run_case("guest forbidden", _sample_input(role="guest"), False, "无权调用 quote_calculate"),
        _run_case("missing items", _sample_input(role="sales", include_items=False), False, "缺少明细 items"),
    ]
    if all(checks):
        print("[MCP self-check] all checks passed")
    else:
        print("[MCP self-check] some checks failed")


if __name__ == "__main__":
    main()
