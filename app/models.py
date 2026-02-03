from __future__ import annotations

from pydantic import BaseModel, Field, ConfigDict


class Message(BaseModel):
    role: str
    content: str


class GatewayRequest(BaseModel):
    model_config = ConfigDict(extra="allow", validate_by_name=True)

    model: str
    messages: list[Message]
    stream: bool = True
    summary_model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = Field(default=None, alias="max_tokens")
    top_p: float | None = None
    stop: list[str] | str | None = None
