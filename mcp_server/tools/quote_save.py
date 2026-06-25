from __future__ import annotations

import copy
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp_server.audit import write_audit_log
from mcp_server.auth import require_tool_permission
from mcp_server.sanitizer import sanitize_quote_save_result
from mcp_server.schemas import normalize_user_context, validate_quote_save_input


TOOL_NAME = "quote_save"
QUOTE_SAVE_STORE_PATH = Path("data") / "mcp_saved_quotes.jsonl"


def _today_key(now: datetime | None = None) -> str:
    current = now or datetime.now()
    return current.strftime("%Y%m%d")


def _iter_store_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


def _next_quote_id(path: Path, now: datetime | None = None) -> str:
    day = _today_key(now)
    max_seq = 0
    prefix = f"Q-{day}-"
    for record in _iter_store_records(path):
        quote_id = str(record.get("quote_id") or "")
        if not quote_id.startswith(prefix):
            continue
        try:
            seq = int(quote_id.rsplit("-", 1)[-1])
        except ValueError:
            continue
        max_seq = max(max_seq, seq)
    return f"{prefix}{max_seq + 1:04d}"


def _extract_total_price(quote_result: dict[str, Any]) -> float | None:
    for key in ("total_price", "exw_price", "fob_price", "total"):
        try:
            value = quote_result.get(key)
            if value is not None:
                return round(float(value), 2)
        except (TypeError, ValueError):
            pass
    tiers = quote_result.get("tiers")
    if isinstance(tiers, list):
        for tier in tiers:
            if not isinstance(tier, dict):
                continue
            for key in ("total_price", "exw_price", "fob_price", "total"):
                try:
                    value = tier.get(key)
                    if value is not None:
                        return round(float(value), 2)
                except (TypeError, ValueError):
                    pass
    return None


def _save_record(
    *,
    user_context: dict[str, Any],
    quote_result: dict[str, Any],
    path: Path = QUOTE_SAVE_STORE_PATH,
    now: datetime | None = None,
) -> dict[str, Any]:
    created_at = (now or datetime.now()).isoformat()
    quote_id = _next_quote_id(path, now)
    locked_quote = copy.deepcopy(quote_result)
    locked_quote["quote_id"] = quote_id
    locked_quote["locked"] = True

    record = {
        "quote_id": quote_id,
        "created_at": created_at,
        "user_id": user_context.get("user_id"),
        "role": user_context.get("role", "guest"),
        "session_id": user_context.get("session_id"),
        "locked": True,
        "quote_result": locked_quote,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return {
        "quote_id": quote_id,
        "status": "saved",
        "locked": True,
        "created_at": created_at,
        "total_price": _extract_total_price(locked_quote),
    }


def _audit_record(
    user_context: dict[str, Any],
    result: dict[str, Any] | None,
    success: bool,
    error: str | None = None,
) -> dict[str, Any]:
    result_dict = result if isinstance(result, dict) else {}
    return {
        "tool": TOOL_NAME,
        "user_id": user_context.get("user_id"),
        "role": user_context.get("role", "guest"),
        "session_id": user_context.get("session_id"),
        "quote_id": result_dict.get("quote_id"),
        "total_price": result_dict.get("total_price"),
        "success": success,
        "error": error,
    }


def _failure(error: str) -> dict[str, Any]:
    return {
        "ok": False,
        "tool": TOOL_NAME,
        "error": error,
    }


def quote_save(input_data: dict) -> dict:
    user_context = normalize_user_context(
        input_data.get("user_context") if isinstance(input_data, dict) else {}
    )
    save_result: dict[str, Any] | None = None
    try:
        require_tool_permission(user_context, TOOL_NAME)
        user_context, query = validate_quote_save_input(input_data)

        save_result = _save_record(
            user_context=user_context,
            quote_result=query["quote_result"],
            path=QUOTE_SAVE_STORE_PATH,
        )
        write_audit_log(_audit_record(user_context, save_result, success=True))
        return {
            "ok": True,
            "tool": TOOL_NAME,
            "result": sanitize_quote_save_result(save_result, user_context.get("role", "sales")),
        }
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
        try:
            write_audit_log(_audit_record(user_context, save_result, success=False, error=error))
        except Exception:
            pass
        return _failure(error)
