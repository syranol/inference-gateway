from __future__ import annotations

from pydantic import BaseModel, Field


class Message(BaseModel):
    role: str
    content: str


class GatewayRequest(BaseModel):
    model: str
    messages: list[Message]
    stream: bool = True
    summary_model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = Field(default=None, alias="max_tokens")
    top_p: float | None = None
    stop: list[str] | str | None = None

    class Config:
        extra = "allow"
        allow_population_by_field_name = True
