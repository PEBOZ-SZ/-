"""业务员编号/姓名：从上传表 quote_params 提取、合并展示（sales_display）。"""
from __future__ import annotations

import re
from typing import Any

SALES_CODE_ALIASES: tuple[str, ...] = (
    "业务员编号",
    "编号",
    "sales_code",
    "salesperson_id",
    "sales_id",
    "seller_id",
    "staff_id",
)

SALES_NAME_ALIASES: tuple[str, ...] = (
    "业务员姓名",
    "业务员",
    "销售姓名",
    "sales_name",
    "salesperson",
    "salesperson_name",
    "seller_name",
    "staff_name",
)

LOCAL_SALES_ID_PREFIX = "local:"

_COMBINED_SALES_RE = re.compile(
    r"^\s*(?P<code>[^\s/|，,、\-_：:]+)\s*[-\s/|，,、_：:]+\s*(?P<name>.+?)\s*$"
)


def normalize_field_key(text: str) -> str:
    """与 demand_parser._normalise_key 对齐，便于匹配上传表表头。"""
    if text is None:
        return ""
    cleaned = str(text).strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"[（）()\[\]【】%]", "", cleaned)
    cleaned = re.sub(r"\s+", "", cleaned)
    for ch in ("/", "\\", ",", "，", ":", "：", ".", "。"):
        cleaned = cleaned.replace(ch, "")
    return cleaned.lower()


def pick_section_value(
    section: dict[str, Any] | None,
    *candidates: str,
    exclude_key_substrings: tuple[str, ...] = (),
) -> str:
    if not isinstance(section, dict):
        return ""
    norm_map: dict[str, str] = {}
    for raw_key, raw_val in section.items():
        nk = normalize_field_key(str(raw_key or ""))
        val = str(raw_val or "").strip()
        if nk and val and val not in {"-", "—"}:
            norm_map.setdefault(nk, val)
    for label in candidates:
        nk = normalize_field_key(label)
        if nk in norm_map:
            return norm_map[nk]
    for label in candidates:
        nk = normalize_field_key(label)
        if not nk:
            continue
        for key, val in section.items():
            key_n = normalize_field_key(str(key or ""))
            if any(ex in key_n for ex in exclude_key_substrings):
                continue
            v = str(val or "").strip()
            if not v or v in {"-", "—"}:
                continue
            # 仅当表头包含候选标签时才模糊匹配，避免「业务员」命中「业务员编号」。
            if nk in key_n:
                return v
    return ""


def _clean_sales_rep_raw(text: str) -> str:
    t = str(text or "").strip()
    if not t or t in {"-", "—"}:
        return ""
    t = re.sub(r"\s+", " ", t)
    return t.strip(" \t\r\n-—_")


def split_combined_sales(text: str) -> tuple[str, str]:
    """解析同格「编号-姓名」如 23-刘朋 / 23 刘朋 / 20：刘璇 / 20_刘璇。"""
    t = _clean_sales_rep_raw(text)
    if not t:
        return "", ""
    m = _COMBINED_SALES_RE.match(t)
    if m:
        return m.group("code").strip(), m.group("name").strip()
    if re.match(r"^[\w\-]+$", t) and re.search(r"\d", t):
        return t, ""
    return "", t


def is_valid_local_sales_user_id(sales_user_id: str) -> bool:
    sid = str(sales_user_id or "").strip()
    if not sid.startswith(LOCAL_SALES_ID_PREFIX):
        return False
    if sid.startswith(f"{LOCAL_SALES_ID_PREFIX}name:"):
        return bool(sid[len(f"{LOCAL_SALES_ID_PREFIX}name:") :].strip())
    return bool(sid[len(LOCAL_SALES_ID_PREFIX) :].strip())


def local_sales_user_display_name(sales_user_id: str, sales_user_code: str = "") -> str:
    sid = str(sales_user_id or "").strip()
    code = str(sales_user_code or "").strip()
    if sid.startswith(f"{LOCAL_SALES_ID_PREFIX}name:"):
        return sid[len(f"{LOCAL_SALES_ID_PREFIX}name:") :].strip()
    if code:
        return code
    if sid.startswith(LOCAL_SALES_ID_PREFIX):
        return sid[len(LOCAL_SALES_ID_PREFIX) :].strip()
    return sid


def _reconcile_sales_code_name(code: str, name: str) -> tuple[str, str]:
    c = str(code or "").strip()
    n = str(name or "").strip()
    if c and n and c == n:
        c2, n2 = split_combined_sales(c)
        if c2 and n2:
            return c2, n2
        if c2 and not n2:
            return c2, ""
        if n2 and not c2:
            return "", n2
        if re.fullmatch(r"[\d\w\-]+", c):
            return c, ""
        return c, n
    if c and not n:
        c2, n2 = split_combined_sales(c)
        if n2:
            return c2 or c, n2
        if c2 and not n2:
            return c2, ""
    if n and not c:
        c2, n2 = split_combined_sales(n)
        if c2:
            return c2, n2 or n
    return c, n


def build_sales_identity(
    code: str,
    name: str,
    *,
    identity_source: str = "sheet",
) -> dict[str, str]:
    c = str(code or "").strip()
    n = str(name or "").strip()
    c, n = _reconcile_sales_code_name(c, n)
    if c and n:
        if c == n:
            n = ""
        elif n in c:
            c, n = split_combined_sales(c)
    if c and n:
        label = format_sales_display(c, n)
        return {
            "sales_user_id": f"{LOCAL_SALES_ID_PREFIX}{c}",
            "sales_user_code": c,
            "sales_user_name": n,
            "sales_user_label": label,
            "identity_source": identity_source,
        }
    if c:
        return {
            "sales_user_id": f"{LOCAL_SALES_ID_PREFIX}{c}",
            "sales_user_code": c,
            "sales_user_name": c,
            "sales_user_label": c,
            "identity_source": identity_source,
        }
    if n:
        return {
            "sales_user_id": f"{LOCAL_SALES_ID_PREFIX}name:{n}",
            "sales_user_code": "",
            "sales_user_name": n,
            "sales_user_label": n,
            "identity_source": identity_source,
        }
    return {}


def normalize_sales_rep(raw: str, *, identity_source: str = "sheet") -> dict[str, str]:
    text = _clean_sales_rep_raw(raw)
    if not text:
        return {}
    code, name = split_combined_sales(text)
    return build_sales_identity(code, name, identity_source=identity_source)


def identity_from_extracted_fields(
    code: str,
    name: str,
    *,
    identity_source: str = "sheet",
) -> dict[str, str]:
    return build_sales_identity(code, name, identity_source=identity_source)


def identity_from_quote_params(quote_params: dict[str, Any] | None) -> dict[str, str]:
    fields = extract_sales_fields(quote_params)
    return identity_from_extracted_fields(
        fields.get("sales_code") or "",
        fields.get("sales_name") or "",
        identity_source="sheet",
    )


def resolve_local_sales_identity(
    cookie_header: str | None,
    payload: dict[str, Any] | None = None,
) -> dict[str, str]:
    """非企微模式身份解析：payload 手工/表格 > Cookie 历史。"""
    if isinstance(payload, dict):
        raw_input = str(payload.get("sales_rep_input") or "").strip()
        if raw_input:
            ident = normalize_sales_rep(raw_input, identity_source="manual")
            if ident:
                return ident

        sid = str(payload.get("sales_user_id") or "").strip()
        if is_valid_local_sales_user_id(sid):
            code = str(payload.get("sales_user_code") or "").strip()
            name = str(payload.get("sales_user_name") or payload.get("sales_user_label") or "").strip()
            if not name:
                name = local_sales_user_display_name(sid, code)
            return {
                "sales_user_id": sid,
                "sales_user_code": code,
                "sales_user_name": name,
                "sales_user_label": format_sales_display(code, name) if code or name else name or sid,
                "identity_source": str(payload.get("identity_source") or "browser"),
            }

        code = str(payload.get("sales_code") or "").strip()
        name = str(payload.get("sales_name") or "").strip()
        if code or name:
            ident = identity_from_extracted_fields(code, name, identity_source="sheet")
            if ident:
                return ident

        ident = identity_from_quote_params(payload.get("quote_params"))
        if ident:
            return ident

    from session_quote_context import parse_sales_user_id_from_cookie, parse_sales_user_name_from_cookie

    cookie_id = parse_sales_user_id_from_cookie(cookie_header)
    if is_valid_local_sales_user_id(cookie_id):
        cookie_name = str(parse_sales_user_name_from_cookie(cookie_header) or "").strip()
        code = ""
        name = cookie_name
        if cookie_id.startswith(f"{LOCAL_SALES_ID_PREFIX}name:"):
            name = cookie_id[len(f"{LOCAL_SALES_ID_PREFIX}name:") :].strip()
        elif cookie_id.startswith(LOCAL_SALES_ID_PREFIX):
            code = cookie_id[len(LOCAL_SALES_ID_PREFIX) :].strip()
            if not name:
                name = code
        return {
            "sales_user_id": cookie_id,
            "sales_user_code": code,
            "sales_user_name": name or cookie_name,
            "sales_user_label": format_sales_display(code, name or cookie_name),
            "identity_source": "browser",
        }
    return {}


def format_sales_display(code: str, name: str) -> str:
    c = str(code or "").strip()
    n = str(name or "").strip()
    if not c and not n:
        return "-"
    if c and n:
        if c == n:
            return c
        if n in c or re.search(r"[-\s/|，,、]", c):
            return c
        return f"{c}-{n}"
    return c or n


def extract_sales_fields(quote_params: dict[str, Any] | None) -> dict[str, str]:
    sec_a: dict[str, Any] = {}
    if isinstance(quote_params, dict):
        raw = quote_params.get("A") or quote_params.get("a")
        if isinstance(raw, dict):
            sec_a = raw

    code = pick_section_value(sec_a, *SALES_CODE_ALIASES)
    name = pick_section_value(
        sec_a,
        *SALES_NAME_ALIASES,
        exclude_key_substrings=("编号", "code", "id"),
    )

    code, name = _reconcile_sales_code_name(code, name)

    return {
        "sales_code": code,
        "sales_name": name,
        "sales_display": format_sales_display(code, name),
    }


def enrich_quote_sales_fields(quote: dict[str, Any]) -> None:
    """就地补全 quote 上的 sales_code / sales_name / sales_display。"""
    if not isinstance(quote, dict):
        return
    extracted = extract_sales_fields(quote.get("quote_params"))
    if not str(quote.get("sales_code") or "").strip():
        quote["sales_code"] = extracted["sales_code"]
    if not str(quote.get("sales_name") or "").strip():
        quote["sales_name"] = extracted["sales_name"]
    quote["sales_display"] = format_sales_display(
        str(quote.get("sales_code") or ""),
        str(quote.get("sales_name") or ""),
    )


def merge_quote_sales_from_payload(quote: dict[str, Any], payload: dict[str, Any]) -> None:
    """报价结果入库/返回前：保留 quote_params 并写入业务员字段。"""
    if not isinstance(quote, dict) or not isinstance(payload, dict):
        return
    qp = payload.get("quote_params")
    if isinstance(qp, dict) and qp:
        quote["quote_params"] = qp
    for key in ("sales_code", "sales_name"):
        val = payload.get(key)
        if val is not None and str(val).strip():
            quote[key] = str(val).strip()
    enrich_quote_sales_fields(quote)


def apply_sales_fields_to_payload(payload: dict[str, Any]) -> None:
    """解析完成后把业务员字段写入 payload（供后续 merge）。"""
    if not isinstance(payload, dict):
        return
    fields = extract_sales_fields(payload.get("quote_params"))
    for key, val in fields.items():
        if key == "sales_display":
            continue
        if val:
            payload[key] = val
