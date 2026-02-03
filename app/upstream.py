from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncGenerator

import httpx

from .config import Settings


class UpstreamError(RuntimeError):
    pass


class UpstreamClient:
    """HTTP client wrapper for the upstream /chat/completions API."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @classmethod
    def from_settings(cls, settings: Settings) -> "UpstreamClient":
        return cls(settings)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._settings.upstream_api_key:
            headers["Authorization"] = f"Bearer {self._settings.upstream_api_key}"
        return headers

    def _should_retry(self, status_code: int | None) -> bool:
        return status_code in {502, 503, 504}

    async def complete(self, payload: dict[str, Any]) -> str:
        """Send a non-streaming completion request and return content text."""
        url = f"{self._settings.upstream_base_url}{self._settings.upstream_path}"
        retries = self._settings.upstream_max_retries
        backoff = self._settings.upstream_retry_backoff
        for attempt in range(retries + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=self._settings.request_timeout
                ) as client:
                    resp = await client.post(url, headers=self._headers(), json=payload)
                if resp.status_code >= 400:
                    if self._should_retry(resp.status_code) and attempt < retries:
                        await asyncio.sleep(backoff * (2**attempt))
                        continue
                    raise UpstreamError(
                        f"Upstream error {resp.status_code}: {resp.text}"
                    )
                data = resp.json()
                break
            except httpx.RequestError as exc:
                if attempt < retries:
                    await asyncio.sleep(backoff * (2**attempt))
                    continue
                raise UpstreamError("Upstream request failed") from exc

        try:
            return data["choices"][0]["message"]["content"]
        except Exception as exc:  # pragma: no cover - defensive
            raise UpstreamError("Unexpected upstream response format") from exc

    async def stream_deltas(
        self, payload: dict[str, Any]
    ) -> AsyncGenerator[tuple[str | None, str | None], None]:
        """Stream delta chunks and yield (reasoning_text, content_text) pairs."""
        url = f"{self._settings.upstream_base_url}{self._settings.upstream_path}"
        retries = self._settings.upstream_max_retries
        backoff = self._settings.upstream_retry_backoff

        for attempt in range(retries + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=self._settings.request_timeout
                ) as client:
                    async with client.stream(
                        "POST", url, headers=self._headers(), json=payload
                    ) as resp:
                        if resp.status_code >= 400:
                            text = await resp.aread()
                            if self._should_retry(resp.status_code) and attempt < retries:
                                await asyncio.sleep(backoff * (2**attempt))
                                continue
                            raise UpstreamError(
                                f"Upstream error {resp.status_code}: {text.decode()}"
                            )

                        async for line in resp.aiter_lines():
                            if not line:
                                continue
                            if not line.startswith("data:"):
                                continue
                            data = line[len("data:") :].strip()
                            if data == "[DONE]":
                                return
                            try:
                                chunk = json.loads(data)
                            except json.JSONDecodeError:
                                continue

                            delta = (
                                chunk.get("choices", [{}])[0]
                                .get("delta", {})
                            )
                            reasoning_text = delta.get("reasoning_content") or delta.get(
                                "reasoning"
                            )
                            content_text = delta.get("content")
                            yield reasoning_text, content_text
                        return
            except httpx.RequestError as exc:
                if attempt < retries:
                    await asyncio.sleep(backoff * (2**attempt))
                    continue
                raise UpstreamError("Upstream request failed") from exc

    async def ping(self) -> bool:
        """Check upstream reachability with a simple GET."""
        url = f"{self._settings.upstream_base_url}/"
        try:
            async with httpx.AsyncClient(timeout=self._settings.summary_timeout) as client:
                resp = await client.get(url)
            return resp.status_code < 500
        except Exception:
            return False
