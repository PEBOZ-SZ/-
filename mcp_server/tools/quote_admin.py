from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp_server.audit import write_audit_log
from mcp_server.auth import require_tool_permission
from mcp_server.sanitizer import sanitize_quote_admin_result
from mcp_server.schemas import normalize_user_context, validate_quote_admin_input
from mcp_server.tools.quote_save import QUOTE_SAVE_STORE_PATH


TOOL_NAME = "quote_admin"
QUOTE_ADMIN_PRICE_RULE_PATH = Path("data") / "mcp_price_rules_admin.jsonl"

VALID_QUOTE_STATUSES = {"draft", "saved", "approved", "exported", "rejected"}


def _now_iso() -> str:
    return datetime.now().isoformat()


def _read_records(path: Path) -> list[dict[str, Any]]:
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


def _write_records(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(record, ensure_ascii=False) for record in records)
    path.write_text(text + ("\n" if text else ""), encoding="utf-8")


def _find_record(records: list[dict[str, Any]], quote_id: str) -> tuple[int, dict[str, Any]]:
    for index, record in enumerate(records):
        if str(record.get("quote_id") or "") == quote_id:
            return index, record
    raise FileNotFoundError(f"quote_id 不存在：{quote_id}")


def _quote_summary(record: dict[str, Any]) -> dict[str, Any]:
    quote = record.get("quote_result") if isinstance(record.get("quote_result"), dict) else {}
    return {
        "product_name": str(quote.get("product_name") or ""),
        "locked": bool(record.get("locked") or quote.get("locked")),
        "frozen": bool(record.get("frozen")),
        "tier_count": len(quote.get("tiers")) if isinstance(quote.get("tiers"), list) else 0,
        "total_price": quote.get("total_price"),
    }


def _current_status(record: dict[str, Any]) -> str:
    status = str(record.get("status") or "saved").strip() or "saved"
    if status not in VALID_QUOTE_STATUSES:
        raise ValueError(f"报价状态不支持：{status}")
    return status


def _ensure_not_frozen(record: dict[str, Any], action_name: str) -> None:
    if record.get("frozen"):
        raise ValueError(f"报价已冻结，不能执行 {action_name}。")


def _transition_quote_legacy(action: str, quote_id: str) -> dict[str, Any]:
    records = _read_records(QUOTE_SAVE_STORE_PATH)
    index, record = _find_record(records, quote_id)
    updated = dict(record)
    updated_at = _now_iso()
    updated["updated_at"] = updated_at

    if action == "approve_quote":
        if updated.get("frozen"):
            raise ValueError("报价已冻结，不能审批。")
        updated["status"] = "approved"
    elif action == "reject_quote":
        if updated.get("frozen"):
            raise ValueError("报价已冻结，不能拒绝。")
        updated["status"] = "rejected"
    elif action == "freeze_quote":
        updated["frozen"] = True
        updated["status"] = str(updated.get("status") or "saved")
    elif action == "unfreeze_quote":
        updated["frozen"] = False
        updated["status"] = str(updated.get("status") or "saved")
    elif action == "view_quote":
        return {
            "action": action,
            "quote_id": quote_id,
            "status": str(updated.get("status") or "saved"),
            "updated_at": updated_at,
            "frozen": bool(updated.get("frozen")),
            "quote_summary": _quote_summary(updated),
        }
    else:
        raise ValueError("不支持的 quote action。")

    records[index] = updated
    _write_records(QUOTE_SAVE_STORE_PATH, records)
    return {
        "action": action,
        "quote_id": quote_id,
        "status": str(updated.get("status") or "saved"),
        "updated_at": updated_at,
        "frozen": bool(updated.get("frozen")),
    }


def _transition_quote(action: str, quote_id: str) -> dict[str, Any]:
    records = _read_records(QUOTE_SAVE_STORE_PATH)
    index, record = _find_record(records, quote_id)
    updated = dict(record)
    updated_at = _now_iso()
    updated["updated_at"] = updated_at
    status = _current_status(updated)

    if action == "approve_quote":
        _ensure_not_frozen(updated, "approve_quote")
        if status == "exported":
            raise ValueError("已 exported 的报价不能再次 approve。")
        if status not in {"draft", "saved"}:
            raise ValueError("只有 draft 或 saved 状态可以 approve。")
        updated["status"] = "approved"
    elif action == "reject_quote":
        _ensure_not_frozen(updated, "reject_quote")
        if status == "exported":
            raise ValueError("已 exported 的报价不能 reject。")
        if status not in {"draft", "saved", "approved"}:
            raise ValueError("只有 draft、saved 或 approved 状态可以 reject。")
        updated["status"] = "rejected"
    elif action == "mark_exported":
        _ensure_not_frozen(updated, "mark_exported")
        if status != "approved":
            raise ValueError("只有 approved 状态可以 mark_exported。")
        updated["status"] = "exported"
    elif action == "freeze_quote":
        updated["frozen"] = True
        updated["status"] = status
    elif action == "unfreeze_quote":
        updated["frozen"] = False
        updated["status"] = status
    elif action == "view_quote":
        return {
            "action": action,
            "quote_id": quote_id,
            "status": status,
            "updated_at": updated_at,
            "frozen": bool(updated.get("frozen")),
            "quote_summary": _quote_summary(updated),
        }
    else:
        raise ValueError("不支持的 quote action。")

    records[index] = updated
    _write_records(QUOTE_SAVE_STORE_PATH, records)
    return {
        "action": action,
        "quote_id": quote_id,
        "status": str(updated.get("status") or status),
        "updated_at": updated_at,
        "frozen": bool(updated.get("frozen")),
    }


def _update_price_rule(user_context: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    updated_at = _now_iso()
    record = {
        "updated_at": updated_at,
        "user_id": user_context.get("user_id"),
        "role": user_context.get("role"),
        "rule": str(payload.get("rule") or payload.get("name") or "").strip(),
        "payload_keys": sorted(payload.keys()),
        "status": "rule_updated",
    }
    QUOTE_ADMIN_PRICE_RULE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with QUOTE_ADMIN_PRICE_RULE_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return {
        "action": "update_price_rule",
        "quote_id": "",
        "status": "rule_updated",
        "updated_at": updated_at,
    }


def _audit_record(
    user_context: dict[str, Any],
    action: str,
    quote_id: str,
    status: str = "",
    success: bool = False,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "tool": TOOL_NAME,
        "user_id": user_context.get("user_id"),
        "role": user_context.get("role", "guest"),
        "session_id": user_context.get("session_id"),
        "action": action,
        "quote_id": quote_id,
        "status": status,
        "success": success,
        "error": error,
    }


def _failure(error: str) -> dict[str, Any]:
    return {"ok": False, "tool": TOOL_NAME, "error": error}


def quote_admin(input_data: dict) -> dict:
    user_context = normalize_user_context(
        input_data.get("user_context") if isinstance(input_data, dict) else {}
    )
    action = ""
    quote_id = ""
    try:
        user_context, query = validate_quote_admin_input(input_data)
        action = query["action"]
        quote_id = query["quote_id"]
        role = str(user_context.get("role") or "guest")
        require_tool_permission(user_context, TOOL_NAME, action=action)

        if action == "update_price_rule":
            result = _update_price_rule(user_context, query.get("payload") or {})
        else:
            result = _transition_quote(action, quote_id)
        write_audit_log(
            _audit_record(
                user_context,
                action,
                quote_id,
                status=str(result.get("status") or ""),
                success=True,
            )
        )
        return {
            "ok": True,
            "tool": TOOL_NAME,
            "result": sanitize_quote_admin_result(result, role),
        }
    except Exception as exc:  # noqa: BLE001
        error = str(exc)
        try:
            write_audit_log(_audit_record(user_context, action, quote_id, success=False, error=error))
        except Exception:
            pass
        return _failure(error)
