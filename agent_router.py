from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from mcp_server.tools.quote_admin import quote_admin
from mcp_server.tools.quote_calculate import quote_calculate
from mcp_server.tools.quote_explain import quote_explain
from mcp_server.tools.quote_export import quote_export
from mcp_server.tools.quote_patch_preview import quote_patch_preview
from mcp_server.tools.quote_save import quote_save


AGENT_TRACE_PATH = Path("logs") / "agent_trace.jsonl"


def _now_iso() -> str:
    return datetime.now().isoformat()


def _default_user_context(context: dict[str, Any]) -> dict[str, Any]:
    raw = context.get("user_context") if isinstance(context.get("user_context"), dict) else {}
    return {
        "user_id": raw.get("user_id") or "sales_001",
        "role": raw.get("role") or "sales",
        "session_id": raw.get("session_id") or "agent_session",
    }


def _extract_quantity(text: str) -> int | None:
    match = re.search(r"(\d+)\s*(?:个|件|pcs|PCS)?", text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _mock_llm_parse_intent(user_input: str) -> dict[str, Any]:
    text = str(user_input or "").strip()
    if any(word in text for word in ("审批", "批准", "驳回", "冻结", "解冻", "管理员")):
        intent = "admin"
    elif any(word in text for word in ("导出", "下载", "PDF", "pdf", "Excel", "excel")):
        intent = "export"
    elif any(word in text for word in ("保存", "落库", "正式报价")):
        intent = "save"
    elif any(word in text for word in ("解释", "说明", "为什么")):
        intent = "explain"
    elif any(word in text for word in ("太贵", "降价", "降一点", "便宜", "修改", "调整")):
        intent = "patch"
    else:
        intent = "quote"
    return {
        "intent": intent,
        "parameters": {
            "quantity": _extract_quantity(text),
            "product_name": "背包" if "背包" in text else "",
            "user_input": text,
        },
    }


def _quote_result(context: dict[str, Any]) -> dict[str, Any]:
    quote_result = context.get("quote_result")
    if isinstance(quote_result, dict) and quote_result:
        return quote_result
    return {
        "product_name": "测试背包",
        "tiers": [{"quantity": 300, "exw_price": 88.9, "processing_fee": 12}],
        "items": [{"name": "测试面料", "spec": "600D", "amount": 10}],
        "total_price": 88.9,
    }


def _quote_id(context: dict[str, Any]) -> str:
    return str(context.get("quote_id") or "Q-20260124-0001")


def _build_tool_input(
    intent: str,
    parameters: dict[str, Any],
    context: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    user_context = _default_user_context(context)
    quantity = parameters.get("quantity") or 300
    quote_result = _quote_result(context)

    if intent == "quote":
        return "quote_calculate", {
            "user_context": user_context,
            "payload": {
                "product_name": parameters.get("product_name") or "测试背包",
                "quantities": [int(quantity)],
                "items": [
                    {
                        "name": "测试面料",
                        "spec": "600D",
                        "usage": "1码²",
                        "unit_price": "10元/码²",
                        "amount": 10,
                    }
                ],
                "mold_fee": 0,
                "processing_fee": 12,
                "system_overhead": 4,
                "gross_margin_rate": 0.35,
                "include_fob": True,
            },
        }
    if intent == "explain":
        return "quote_explain", {
            "user_context": user_context,
            "query": {
                "user_question": parameters.get("user_input") or "帮我解释这个报价",
                "quote_result": quote_result,
                "audience": "sales_internal",
            },
        }
    if intent == "patch":
        return "quote_patch_preview", {
            "user_context": user_context,
            "query": {
                "quote_result": quote_result,
                "patch": {"processing_fee_delta": -0.5},
            },
        }
    if intent == "save":
        return "quote_save", {
            "user_context": user_context,
            "query": {"quote_result": quote_result},
        }
    if intent == "export":
        return "quote_export", {
            "user_context": user_context,
            "query": {"quote_id": _quote_id(context)},
        }
    if intent == "admin":
        return "quote_admin", {
            "user_context": user_context,
            "query": {
                "action": "approve_quote",
                "quote_id": _quote_id(context),
                "payload": {"reason": parameters.get("user_input") or "agent request"},
            },
        }
    raise ValueError(f"不支持的 intent：{intent}")


def _tool_map() -> dict[str, Callable[[dict], dict]]:
    return {
        "quote_calculate": quote_calculate,
        "quote_explain": quote_explain,
        "quote_patch_preview": quote_patch_preview,
        "quote_save": quote_save,
        "quote_export": quote_export,
        "quote_admin": quote_admin,
    }


def _write_agent_trace(
    *,
    user_input: str,
    intent: str,
    tool_called: str,
    success: bool,
    error: str | None = None,
) -> None:
    AGENT_TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "user_input": user_input,
        "intent": intent,
        "tool_called": tool_called,
        "timestamp": _now_iso(),
        "success": success,
        "error": error,
    }
    with AGENT_TRACE_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def run_agent(user_input: str, context: dict | None = None) -> dict:
    context_dict = context if isinstance(context, dict) else {}
    intent = ""
    tool_called = ""
    try:
        parsed = _mock_llm_parse_intent(user_input)
        intent = str(parsed.get("intent") or "quote")
        parameters = parsed.get("parameters") if isinstance(parsed.get("parameters"), dict) else {}
        tool_called, tool_input = _build_tool_input(intent, parameters, context_dict)
        result = _tool_map()[tool_called](tool_input)
        success = bool(result.get("ok")) if isinstance(result, dict) else False
        _write_agent_trace(
            user_input=str(user_input or ""),
            intent=intent,
            tool_called=tool_called,
            success=success,
            error=None if success else str((result or {}).get("error", "")),
        )
        return {
            "intent": intent,
            "tool_called": tool_called,
            "result": result,
        }
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
        _write_agent_trace(
            user_input=str(user_input or ""),
            intent=intent,
            tool_called=tool_called,
            success=False,
            error=error,
        )
        return {
            "intent": intent or "unknown",
            "tool_called": tool_called,
            "result": {"ok": False, "error": error},
        }
