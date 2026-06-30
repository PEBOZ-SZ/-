from __future__ import annotations

from typing import Any

import quote_upload_storage
from mcp_server.audit import write_audit_log
from mcp_server.auth import ROLE_SALES, require_tool_permission
from mcp_server.sanitizer import sanitize_quote_approval_status_result
from mcp_server.schemas import normalize_user_context, validate_quote_approval_status_input


TOOL_NAME = "quote_approval_status"
SAFE_NOT_FOUND = "报价不存在或无权访问。"


def _failure(error: str) -> dict[str, Any]:
    return {"ok": False, "tool": TOOL_NAME, "error": error}


def _resolve_detail(query: dict[str, Any]) -> dict[str, Any] | None:
    return quote_upload_storage.load_quote_detail_for_mcp(
        quote_uid=query["quote_uid"],
        calc_quote_id=query["calc_quote_id"],
        version_id=query["version_id"],
        version_no=query["version_no"],
        include_quote_json=True,
        include_files=False,
        include_chat_messages=False,
    )


def _quote_summary(detail: dict[str, Any]) -> dict[str, Any]:
    quote = detail.get("quote_result") if isinstance(detail.get("quote_result"), dict) else {}
    tiers = quote.get("tiers") if isinstance(quote.get("tiers"), list) else []
    return {
        "product_name": str(detail.get("product_name") or quote.get("product_name") or ""),
        "tier_count": len(tiers),
        "material_total": quote.get("material_total"),
    }


def _feedback_type(status: str, admin_feedback: dict[str, Any]) -> str:
    if status == "rejected":
        return "rejected"
    if status == "approved":
        return "approved"
    if status == "frozen":
        return "frozen"
    if status == "exported":
        return "exported"
    if admin_feedback.get("has_admin_correction"):
        return "admin_corrected"
    if admin_feedback.get("has_admin_update") or admin_feedback.get("has_feedback"):
        return "admin_feedback"
    return "none"


def _admin_feedback_summary(detail: dict[str, Any]) -> dict[str, Any]:
    quote = detail.get("quote_result") if isinstance(detail.get("quote_result"), dict) else {}
    admin_feedback = detail.get("admin_feedback") if isinstance(detail.get("admin_feedback"), dict) else {}
    status = str(detail.get("approval_status") or "pending").strip().lower() or "pending"
    note = str(detail.get("approval_note") or admin_feedback.get("approval_note") or "").strip()
    feedback_type = _feedback_type(status, admin_feedback)
    try:
        version_no = int(detail.get("version_no") or 0)
    except (TypeError, ValueError):
        version_no = 0
    has_corrected_quote = bool(admin_feedback.get("has_visual_correction")) or version_no > 1
    corrected_at = str(admin_feedback.get("admin_update_at") or admin_feedback.get("approved_at") or "").strip()
    product_name = str(detail.get("product_name") or quote.get("product_name") or "").strip()
    if note:
        summary = note
    elif has_corrected_quote and product_name:
        summary = f"管理员修正报价：{product_name}"
    elif feedback_type == "approved":
        summary = "报价已审批通过。"
    elif feedback_type == "frozen":
        summary = "报价已冻结。"
    elif feedback_type == "exported":
        summary = "报价已标记为已导出。"
    elif feedback_type == "admin_feedback":
        summary = "管理员有新的反馈。"
    else:
        summary = ""
    return {
        "has_feedback": feedback_type != "none",
        "feedback_type": feedback_type,
        "summary": summary,
        "has_admin_corrected_quote": has_corrected_quote,
        "admin_corrected_at": corrected_at,
    }


def _export_readiness(detail: dict[str, Any]) -> dict[str, Any]:
    status = str(detail.get("approval_status") or "pending").strip().lower() or "pending"
    if status in {"approved", "exported"}:
        return {
            "can_export": True,
            "reason": "approval_status allows export",
            "next_action_hint": "可以继续导出或发送给客户。",
        }
    if status == "rejected":
        return {
            "can_export": False,
            "reason": "approval_status=rejected",
            "next_action_hint": "请查看管理员驳回原因并调整报价。",
        }
    if status == "frozen":
        return {
            "can_export": False,
            "reason": "approval_status=frozen",
            "next_action_hint": "报价已冻结，请联系管理员处理。",
        }
    return {
        "can_export": False,
        "reason": f"approval_status={status}",
        "next_action_hint": "请等待管理员审批或查看管理员反馈。",
    }


def _result_from_detail(detail: dict[str, Any], query: dict[str, Any]) -> dict[str, Any]:
    admin_feedback = detail.get("admin_feedback") if isinstance(detail.get("admin_feedback"), dict) else {}
    result = {
        "quote_uid": str(detail.get("quote_uid") or ""),
        "calc_quote_id": str(detail.get("calc_quote_id") or ""),
        "version_id": detail.get("version_id"),
        "version_no": detail.get("version_no"),
        "approval_status": str(detail.get("approval_status") or "pending").strip().lower() or "pending",
        "approval_note": str(detail.get("approval_note") or ""),
        "approval_updated_at": str(admin_feedback.get("approved_at") or ""),
        "approved_by": str(admin_feedback.get("approved_by") or ""),
        "quote_summary": _quote_summary(detail),
    }
    if query["include_admin_feedback"]:
        result["admin_feedback"] = _admin_feedback_summary(detail)
    if query["include_export_readiness"]:
        result["export_readiness"] = _export_readiness(detail)
    return result


def _audit_record(
    user_context: dict[str, Any],
    query: dict[str, Any],
    result: dict[str, Any] | None = None,
    success: bool = False,
    error: str | None = None,
) -> dict[str, Any]:
    result_dict = result if isinstance(result, dict) else {}
    feedback = result_dict.get("admin_feedback") if isinstance(result_dict.get("admin_feedback"), dict) else {}
    readiness = result_dict.get("export_readiness") if isinstance(result_dict.get("export_readiness"), dict) else {}
    return {
        "tool": TOOL_NAME,
        "user_id": user_context.get("user_id"),
        "role": user_context.get("role", "guest"),
        "session_id": user_context.get("session_id"),
        "sales_user_id": user_context.get("sales_user_id"),
        "quote_uid": result_dict.get("quote_uid") or query.get("quote_uid") or "",
        "calc_quote_id": result_dict.get("calc_quote_id") or query.get("calc_quote_id") or "",
        "version_id": result_dict.get("version_id") or query.get("version_id"),
        "version_no": result_dict.get("version_no") or query.get("version_no"),
        "approval_status": result_dict.get("approval_status") or "",
        "feedback_type": feedback.get("feedback_type") or "",
        "can_export": readiness.get("can_export"),
        "success": success,
        "error": error,
    }


def quote_approval_status(input_data: dict) -> dict:
    user_context = normalize_user_context(
        input_data.get("user_context") if isinstance(input_data, dict) else {}
    )
    query: dict[str, Any] = {}
    result: dict[str, Any] | None = None
    try:
        require_tool_permission(user_context, TOOL_NAME)
        user_context, query = validate_quote_approval_status_input(input_data)

        role = str(user_context.get("role") or "guest")
        sales_user_id = str(user_context.get("sales_user_id") or "").strip()
        if role == ROLE_SALES and not sales_user_id:
            raise ValueError("role=sales requires sales_user_id.")

        detail = _resolve_detail(query)
        if not detail:
            raise PermissionError(SAFE_NOT_FOUND)
        quote_uid = str(detail.get("quote_uid") or "").strip()
        if role == ROLE_SALES and not quote_upload_storage.sales_user_can_access_quote(quote_uid, sales_user_id):
            raise PermissionError(SAFE_NOT_FOUND)

        result = _result_from_detail(detail, query)
        write_audit_log(_audit_record(user_context, query, result=result, success=True))
        return {
            "ok": True,
            "tool": TOOL_NAME,
            "result": sanitize_quote_approval_status_result(result, role),
        }
    except Exception as exc:  # noqa: BLE001
        error = SAFE_NOT_FOUND if isinstance(exc, PermissionError) and str(exc) == SAFE_NOT_FOUND else str(exc)
        try:
            write_audit_log(_audit_record(user_context, query, result=result, success=False, error=error))
        except Exception:
            pass
        return _failure(error)
