from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


AUDIT_LOG_PATH = Path("logs") / "mcp_audit.jsonl"


def write_audit_log(record: dict) -> None:
    """Append one JSONL audit record for MCP tool calls."""
    log_record = dict(record or {})
    log_record.setdefault("timestamp", datetime.now(timezone.utc).isoformat())

    AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(log_record, ensure_ascii=False) + "\n")
