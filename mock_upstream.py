from __future__ import annotations

import json
import asyncio
from typing import Any, AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI()


def _summarize_text(text: str, max_words: int = 20) -> str:
    words = text.split()
    snippet = " ".join(words[:max_words])
    return f"Summary: {snippet}{'...' if len(words) > max_words else ''}"


def _build_stream_payload() -> str:
    reasoning = (
        "<analysis>We need to answer the user's question. "
        "We'll recall relevant facts and provide a concise explanation.</analysis>"
    )
    final = (
        "<final>The sky is blue because shorter blue wavelengths are scattered more "
        "by the atmosphere, making blue light reach our eyes from many directions.</final>"
    )
    return reasoning + final


async def _event_stream(text: str) -> AsyncGenerator[str, None]:
    chunk_size = 24
    for i in range(0, len(text), chunk_size):
        chunk = text[i : i + chunk_size]
        data = {
            "choices": [
                {
                    "delta": {
                        "content": chunk,
                    }
                }
            ]
        }
        yield f"data: {json.dumps(data)}\n\n"
        await asyncio.sleep(0.01)
    yield "data: [DONE]\n\n"


@app.post("/chat/completions")
async def chat_completions(request: Request):
    body: dict[str, Any] = await request.json()
    stream = body.get("stream", False)

    if stream:
        payload = _build_stream_payload()
        return StreamingResponse(_event_stream(payload), media_type="text/event-stream")

    messages = body.get("messages", [])
    prompt = "\n".join(f"{m.get('role')}: {m.get('content')}" for m in messages)
    summary = _summarize_text(prompt)
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": summary,
                }
            }
        ]
    }
