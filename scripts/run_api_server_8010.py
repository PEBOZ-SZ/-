from __future__ import annotations

import sys
from pathlib import Path

import uvicorn


if __name__ == "__main__":
    root_dir = Path(__file__).resolve().parents[1]
    if str(root_dir) not in sys.path:
        sys.path.insert(0, str(root_dir))
    log_dir = root_dir / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = (log_dir / "api_pythonw_8010.log").open("a", encoding="utf-8")
    sys.stdout = log_file
    sys.stderr = log_file
    print("[API RUNNER] starting api_server on 127.0.0.1:8010", flush=True)
    uvicorn.run("api_server:app", host="127.0.0.1", port=8010, log_level="info")
