from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    user_id: str = Field(..., min_length=1)
    session_id: str = Field(..., min_length=1)
    role: str = "sales"
    workflow_state: str = "INPUT"
    context: dict[str, Any] = Field(default_factory=dict)


class ApiToolRequest(BaseModel):
    user_context: dict[str, Any] = Field(default_factory=dict)
    workflow_state: str | None = None
    payload: dict[str, Any] | None = None
    query: dict[str, Any] | None = None


class WorkflowActionRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    state: str = "INPUT"
    action: str
    detail: dict[str, Any] = Field(default_factory=dict)


class ApiResponse(BaseModel):
    ok: bool
    result: Any = None
    error: str | None = None
