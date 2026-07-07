from __future__ import annotations

import json
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{12,96}$")
DEFAULT_TTL_HOURS = 24


def _store_dir() -> Path:
    raw = str(os.environ.get("QUOTE_SHEET_PUBLIC_DIR") or "").strip()
    if raw:
        return Path(raw)
    return Path("quote_storage") / "public_quote_sheets"


def _token_path(token: str) -> Path:
    safe = str(token or "").strip()
    if not TOKEN_RE.match(safe):
        raise ValueError("invalid quote sheet token")
    return _store_dir() / f"{safe}.json"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(raw: Any) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def save_public_quote_sheet_prefill(prefill: dict[str, Any], *, ttl_hours: int = DEFAULT_TTL_HOURS) -> str:
    if not isinstance(prefill, dict):
        raise ValueError("prefill must be a dict")
    token = secrets.token_urlsafe(18)
    now = _utc_now()
    ttl = max(1, min(int(ttl_hours or DEFAULT_TTL_HOURS), 168))
    record = {
        "created_at": _iso(now),
        "expires_at": _iso(now + timedelta(hours=ttl)),
        "prefill": prefill,
    }
    root = _store_dir()
    root.mkdir(parents=True, exist_ok=True)
    _token_path(token).write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    cleanup_expired_public_quote_sheets()
    return token


def load_public_quote_sheet_prefill(token: str) -> dict[str, Any] | None:
    try:
        path = _token_path(token)
    except ValueError:
        return None
    if not path.exists() or not path.is_file():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    expires_at = _parse_iso(record.get("expires_at") if isinstance(record, dict) else None)
    if expires_at and expires_at < _utc_now():
        try:
            path.unlink()
        except OSError:
            pass
        return None
    prefill = record.get("prefill") if isinstance(record, dict) else None
    return prefill if isinstance(prefill, dict) else None


def cleanup_expired_public_quote_sheets() -> None:
    root = _store_dir()
    if not root.exists():
        return
    now = _utc_now()
    for path in root.glob("*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            expires_at = _parse_iso(record.get("expires_at") if isinstance(record, dict) else None)
            if expires_at and expires_at < now:
                path.unlink()
        except Exception:
            continue
