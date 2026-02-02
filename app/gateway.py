from __future__ import annotations

import asyncio
import uuid
from typing import Any, AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from .config import Settings, get_settings
from .models import GatewayRequest, Message
from .parsing import TagParser
from .sse import format_sse
from .upstream import UpstreamClient


def _build_prompt_text(messages: list[Message]) -> str:
    return "\n".join(f"{m.role}: {m.content}" for m in messages)


def _build_summary_payload(text: str, model: str, kind: str) -> dict[str, Any]:
    if kind == "prompt":
        system = "You are a concise assistant that summarizes user prompts."
        user = (
            "Summarize the following prompt in 1-2 sentences. "
            "Keep it faithful and brief.\n\n"
            f"Prompt:\n{text}"
        )
    else:
        system = "You are a concise assistant that summarizes reasoning."
        user = (
            "Summarize the following reasoning in 2-3 bullet points. "
            "Focus on the key steps only.\n\n"
            f"Reasoning:\n{text}"
        )

    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "temperature": 0.2,
    }


def _inject_tag_instruction(messages: list[Message]) -> list[dict[str, str]]:
    instruction = (
        "Respond with reasoning inside <analysis>...</analysis> and the final answer "
        "inside <final>...</final>. Output only those tags and their content."
    )
    tagged_messages = [{"role": "system", "content": instruction}]
    tagged_messages.extend({"role": m.role, "content": m.content} for m in messages)
    return tagged_messages


def _build_main_payload(req: GatewayRequest) -> dict[str, Any]:
    payload = req.dict(by_alias=True, exclude_none=True)
    payload["messages"] = _inject_tag_instruction(req.messages)
    payload["stream"] = True
    return payload


async def _consume_stream(
    payload: dict[str, Any],
    upstream: UpstreamClient,
    settings: Settings,
    final_queue: asyncio.Queue[str | None],
    reasoning_buffer: list[str],
    analysis_done: asyncio.Event,
    stream_done: asyncio.Event,
    stream_errors: list[str],
) -> None:
    parser = TagParser()
    raw_chunks: list[str] = []
    used_reasoning_field = False

    try:
        async for reasoning_text, content_text in upstream.stream_deltas(payload):
            if reasoning_text and settings.enable_parse_reasoning:
                used_reasoning_field = True
                reasoning_buffer.append(reasoning_text)
                raw_chunks.append(reasoning_text)

            if content_text:
                raw_chunks.append(content_text)
                if used_reasoning_field and settings.enable_parse_reasoning:
                    if not analysis_done.is_set():
                        analysis_done.set()
                    await final_queue.put(content_text)
                else:
                    parsed = parser.feed(content_text)
                    if parsed.analysis_chunks:
                        reasoning_buffer.extend(parsed.analysis_chunks)
                    if parsed.analysis_done and not analysis_done.is_set():
                        analysis_done.set()
                    for chunk in parsed.final_chunks:
                        await final_queue.put(chunk)
                    if parsed.final_chunks and not analysis_done.is_set():
                        analysis_done.set()

        if not analysis_done.is_set() and reasoning_buffer:
            analysis_done.set()

        if not used_reasoning_field:
            parsed = parser.finalize()
            if parsed.analysis_chunks:
                reasoning_buffer.extend(parsed.analysis_chunks)
                if not analysis_done.is_set():
                    analysis_done.set()
            for chunk in parsed.final_chunks:
                await final_queue.put(chunk)

            if not parser.seen_any_tag and raw_chunks:
                for chunk in raw_chunks:
                    if chunk:
                        await final_queue.put(chunk)
                if not analysis_done.is_set():
                    analysis_done.set()
    except Exception as exc:  # pragma: no cover - safety
        stream_errors.append(str(exc))
    finally:
        await final_queue.put(None)
        stream_done.set()


def create_app(upstream_client: UpstreamClient | None = None) -> FastAPI:
    settings = get_settings()
    upstream = upstream_client or UpstreamClient.from_settings(settings)
    app = FastAPI()

    @app.get("/healthz")
    async def healthz():
        return {"status": "ok", "scope": "gateway"}

    @app.get("/upstream-health")
    async def upstream_health():
        ok = await upstream.ping()
        return {"status": "ok" if ok else "degraded", "upstream": ok}

    @app.post("/v1/chat/completions")
    async def chat_completions(req: GatewayRequest):
        if settings.allow_models is not None and req.model not in settings.allow_models:
            raise HTTPException(status_code=400, detail="Model not allowed")
        if not req.stream:
            raise HTTPException(status_code=400, detail="stream=true is required")

        request_id = uuid.uuid4().hex
        prompt_text = _build_prompt_text(req.messages)
        summary_model = req.summary_model or settings.summary_model_default or req.model

        prompt_summary_payload = _build_summary_payload(
            prompt_text, summary_model, kind="prompt"
        )
        main_payload = _build_main_payload(req)

        async def event_stream() -> AsyncGenerator[str, None]:
            final_queue: asyncio.Queue[str | None] = asyncio.Queue()
            analysis_done = asyncio.Event()
            stream_done = asyncio.Event()
            reasoning_buffer: list[str] = []
            stream_errors: list[str] = []

            stream_task = asyncio.create_task(
                _consume_stream(
                    main_payload,
                    upstream,
                    settings,
                    final_queue,
                    reasoning_buffer,
                    analysis_done,
                    stream_done,
                    stream_errors,
                )
            )

            prompt_summary_task = asyncio.create_task(
                upstream.complete(prompt_summary_payload)
            )

            try:
                try:
                    prompt_summary = await asyncio.wait_for(
                        prompt_summary_task, timeout=settings.summary_timeout
                    )
                    yield format_sse(
                        "summary.prompt",
                        {"text": prompt_summary, "request_id": request_id},
                    )
                except Exception:
                    yield format_sse(
                        "error",
                        {
                            "message": "prompt summary failed",
                            "stage": "prompt_summary",
                            "request_id": request_id,
                        },
                    )

                wait_tasks = {
                    asyncio.create_task(analysis_done.wait()),
                    asyncio.create_task(stream_done.wait()),
                }
                done, pending = await asyncio.wait(
                    wait_tasks, return_when=asyncio.FIRST_COMPLETED
                )
                for task in pending:
                    task.cancel()

                reasoning_text = "".join(reasoning_buffer)
                if reasoning_text:
                    reasoning_text = reasoning_text[: settings.max_reasoning_chars]
                    reasoning_payload = _build_summary_payload(
                        reasoning_text, summary_model, kind="reasoning"
                    )
                    try:
                        reasoning_summary = await asyncio.wait_for(
                            upstream.complete(reasoning_payload),
                            timeout=settings.summary_timeout,
                        )
                        yield format_sse(
                            "summary.reasoning",
                            {"text": reasoning_summary, "request_id": request_id},
                        )
                    except Exception:
                        yield format_sse(
                            "error",
                            {
                                "message": "reasoning summary failed",
                                "stage": "reasoning_summary",
                                "request_id": request_id,
                            },
                        )
                        yield format_sse(
                            "summary.reasoning",
                            {"text": "", "request_id": request_id},
                        )
                else:
                    yield format_sse(
                        "summary.reasoning",
                        {"text": "", "request_id": request_id},
                    )

                while True:
                    chunk = await final_queue.get()
                    if chunk is None:
                        break
                    yield format_sse(
                        "output.delta",
                        {"text": chunk, "request_id": request_id},
                    )

                if stream_errors:
                    yield format_sse(
                        "error",
                        {
                            "message": stream_errors[0],
                            "stage": "upstream_stream",
                            "request_id": request_id,
                        },
                    )

                yield format_sse("output.done", {"request_id": request_id})
            except asyncio.CancelledError:
                stream_task.cancel()
                prompt_summary_task.cancel()
                raise
            finally:
                if not stream_task.done():
                    stream_task.cancel()
                if not prompt_summary_task.done():
                    prompt_summary_task.cancel()
                try:
                    await stream_task
                except Exception:
                    pass

        return StreamingResponse(
            event_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
        )

    return app
