"""Public API schemas; conversation identifiers are supplied by callers."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_QUERY_LENGTH = 10_000
MAX_SESSION_ID_LENGTH = 128


class ChatRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    query: str = Field(min_length=1, max_length=MAX_QUERY_LENGTH)
    session_id: str = Field(min_length=1, max_length=MAX_SESSION_ID_LENGTH)

    @field_validator("query", "session_id")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Value must not be blank.")
        return value


class ChatResponse(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    response: str


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ReadyResponse(BaseModel):
    status: Literal["ready"] = "ready"
