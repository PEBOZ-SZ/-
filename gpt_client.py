from __future__ import annotations

import os
from typing import Any

from gpt_tool_router import OpenAIToolCallingClient, run_gpt_tool_agent


DEFAULT_API_MODEL = os.environ.get("GPT_API_MODEL", "gpt-5.5")


def run_chat(message: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    client = OpenAIToolCallingClient(model=DEFAULT_API_MODEL)
    return run_gpt_tool_agent(message, context=context, client=client)
