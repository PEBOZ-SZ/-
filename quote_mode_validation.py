from __future__ import annotations

from typing import Any

QUOTE_MODES = frozenset({"demo_mode", "draft_mode", "production_mode"})
ALLOWED_SOURCES = frozenset(
    {
        "user_input",
        "uploaded_bom",
        "price_kb",
        "approved_rule",
        "ai_estimate",
        "default_demo",
    }
)

AMOUNT_FIELD_KEYS = (
    "mold_fee",
    "processing_fee",
    "system_overhead",
    "gross_margin_rate",
    "fob_addition",
)
ITEM_AMOUNT_FIELD_KEYS = ("usage", "unit_price", "amount")

_QUOTE_MODE_ALIASES = {
    "demo": "demo_mode",
    "demo_mode": "demo_mode",
    "draft": "draft_mode",
    "draft_mode": "draft_mode",
    "trial": "draft_mode",
    "trial_mode": "draft_mode",
    "production": "production_mode",
    "production_mode": "production_mode",
    "formal": "production_mode",
    "formal_mode": "production_mode",
}

_SOURCE_ALIASES = {
    "user_input": "user_input",
    "user": "user_input",
    "manual": "user_input",
    "user_edit": "user_input",
    "admin_edit": "user_input",
    "uploaded_bom": "uploaded_bom",
    "bom": "uploaded_bom",
    "sheet": "uploaded_bom",
    "structure_inline": "uploaded_bom",
    "price_kb": "price_kb",
    "kb": "price_kb",
    "knowledge": "price_kb",
    "knowledge_base": "price_kb",
    "approved_rule": "approved_rule",
    "override": "approved_rule",
    "admin": "approved_rule",
    "ai_estimate": "ai_estimate",
    "ai": "ai_estimate",
    "model": "ai_estimate",
    "default_demo": "default_demo",
    "demo": "default_demo",
    "default": "default_demo",
}


def normalize_quote_mode(value: Any) -> str:
    text = str(value or "").strip().lower()
    return _QUOTE_MODE_ALIASES.get(text, "draft_mode")


def normalize_source(value: Any) -> str:
    text = str(value or "").strip().lower()
    return _SOURCE_ALIASES.get(text, "")


def build_source_summary(payload: dict[str, Any], result: dict[str, Any] | None = None) -> dict[str, int]:
    summary = {source: 0 for source in sorted(ALLOWED_SOURCES)}

    def add(value: Any) -> None:
        source = normalize_source(value)
        if source:
            summary[source] += 1

    if isinstance(payload, dict):
        for key, value in payload.items():
            if key == "items":
                continue
            if key == "source" or key.endswith("_source"):
                add(value)
        items = payload.get("items")
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                for key, value in item.items():
                    if key == "source" or key.endswith("_source"):
                        add(value)

    if isinstance(result, dict):
        rows = result.get("detail_rows")
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                for key, value in row.items():
                    if key == "source" or key.endswith("_source"):
                        add(value)

    return {key: value for key, value in summary.items() if value}


def validate_quote_payload_for_mode(
    payload: dict[str, Any],
    *,
    quote_mode: str | None = None,
) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    mode = normalize_quote_mode(quote_mode if quote_mode is not None else data.get("quote_mode"))
    errors: list[dict[str, str]] = []
    source_summary = build_source_summary(data)

    if mode == "production_mode":
        _validate_production_structure(data, errors)
        _validate_production_sources(data, errors)

    if errors:
        status = "blocked"
    elif mode == "draft_mode" and source_summary.get("ai_estimate", 0) > 0:
        status = "review_required"
    else:
        status = "passed"

    return {
        "quote_mode": mode,
        "validation_status": status,
        "validation_errors": errors,
        "source_summary": source_summary,
    }


def _validate_production_structure(data: dict[str, Any], errors: list[dict[str, str]]) -> None:
    items = data.get("items")
    if "items" not in data:
        _add_error(errors, "items_missing", "Production quote requires items.", "items")
    elif not isinstance(items, list):
        _add_error(errors, "items_not_list", "Production quote items must be a list.", "items")
    elif not items:
        _add_error(errors, "items_empty", "Production quote requires at least one item.", "items")

    quantities = data.get("quantities")
    if "quantities" not in data:
        _add_error(errors, "quantities_missing", "Production quote requires quantities.", "quantities")
    elif not _has_quantities(quantities):
        _add_error(errors, "quantities_empty", "Production quote requires at least one quantity.", "quantities")

    if _truthy(data.get("default_line_items")) or _truthy(data.get("uses_default_line_items")):
        _add_error(
            errors,
            "default_line_items_not_allowed",
            "Production quote cannot use default line items.",
            "default_line_items",
        )


def _validate_production_sources(data: dict[str, Any], errors: list[dict[str, str]]) -> None:
    items = data.get("items")
    if isinstance(items, list):
        for index, row in enumerate(items):
            if not isinstance(row, dict):
                continue
            row_source = normalize_source(row.get("source"))
            if row_source in {"default_demo", "ai_estimate"}:
                _add_forbidden_source_error(errors, row_source, f"items[{index}].source")
            for field in ITEM_AMOUNT_FIELD_KEYS:
                if field in row and _field_has_value(row.get(field)):
                    source = _field_source(row, field)
                    if not source:
                        _add_missing_source_error(errors, f"items[{index}].{field}")
                    elif source in {"default_demo", "ai_estimate"}:
                        _add_forbidden_source_error(errors, source, f"items[{index}].{field}")

    for field in AMOUNT_FIELD_KEYS:
        if field not in data or not _field_has_value(data.get(field)):
            _add_error(
                errors,
                f"{field}_missing",
                f"Production quote requires {field}.",
                field,
            )
            continue
        source = _field_source(data, field)
        if not source:
            _add_missing_source_error(errors, field)
        elif source in {"default_demo", "ai_estimate"}:
            _add_forbidden_source_error(errors, source, field)


def _field_source(container: dict[str, Any], field: str, *, fallback: str = "") -> str:
    explicit = normalize_source(container.get(f"{field}_source"))
    if explicit:
        return explicit
    source_map = container.get("field_sources")
    if isinstance(source_map, dict):
        mapped = normalize_source(source_map.get(field))
        if mapped:
            return mapped
    return fallback


def _add_forbidden_source_error(errors: list[dict[str, str]], source: str, path: str) -> None:
    if source == "default_demo":
        _add_error(
            errors,
            "default_demo_not_allowed",
            "Production quote cannot use default_demo source.",
            path,
        )
    elif source == "ai_estimate":
        _add_error(
            errors,
            "ai_estimate_not_allowed",
            "Production quote cannot use ai_estimate source.",
            path,
        )


def _add_missing_source_error(errors: list[dict[str, str]], path: str) -> None:
    _add_error(
        errors,
        "amount_field_source_missing",
        "Production quote amount-impacting field requires source.",
        path,
    )


def _add_error(errors: list[dict[str, str]], code: str, message: str, path: str) -> None:
    errors.append(
        {
            "code": code,
            "message": message,
            "path": path,
            "severity": "error",
        }
    )


def _has_quantities(value: Any) -> bool:
    if not value:
        return False
    if isinstance(value, (list, tuple)):
        return any(_field_has_value(item) for item in value)
    return _field_has_value(value)


def _field_has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    return True


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)
