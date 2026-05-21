"""Chat request/response domain models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class ChatRequest(BaseModel):
    message: str = Field(..., description="User message to the chatbot.")
    session_id: str | None = Field(
        default=None,
        description="Optional session ID. Required for write_memory recall across calls.",
    )

    @field_validator("message")
    @classmethod
    def message_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be empty")
        return value

    @field_validator("session_id")
    @classmethod
    def session_id_valid(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class ToolCallTrace(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result_summary: str
    error: str | None = None


class ChatResponse(BaseModel):
    reply: str
    tool_trace: list[ToolCallTrace] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    refused: bool = False
    refusal_reason: str | None = None
