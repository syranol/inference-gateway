import json
import pytest
import httpx

from app.gateway import create_app


class FakeUpstreamClient:
    async def complete(self, payload):
        content = payload["messages"][1]["content"]
        if "Reasoning:" in content:
            return "REASONING_SUMMARY"
        return "PROMPT_SUMMARY"

    async def stream_deltas(self, payload):
        text = "<analysis>Step 1.</analysis><final>Answer.</final>"
        for chunk in [text[:12], text[12:24], text[24:]]:
            yield None, chunk


class FakeUpstreamClientNoTags(FakeUpstreamClient):
    async def stream_deltas(self, payload):
        for chunk in ["Hello ", "world!"]:
            yield None, chunk


async def _collect_events(client: httpx.AsyncClient, payload: dict):
    events = []
    async with client.stream("POST", "/v1/chat/completions", json=payload) as resp:
        assert resp.status_code == 200
        event = None
        async for line in resp.aiter_lines():
            if not line:
                event = None
                continue
            if line.startswith("event:"):
                event = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data = json.loads(line[len("data:") :].strip())
                events.append((event, data))
    return events


@pytest.mark.asyncio
async def test_ordered_events_with_tags():
    app = create_app(upstream_client=FakeUpstreamClient())
    async with httpx.AsyncClient(app=app, base_url="http://test") as client:
        payload = {
            "model": "reasoning-llm",
            "stream": True,
            "messages": [{"role": "user", "content": "hi"}],
        }
        events = await _collect_events(client, payload)

    event_names = [e[0] for e in events]
    assert event_names[0] == "summary.prompt"
    assert "summary.reasoning" in event_names
    assert "output.delta" in event_names
    assert event_names[-1] == "output.done"


@pytest.mark.asyncio
async def test_missing_tags_falls_back_to_final():
    app = create_app(upstream_client=FakeUpstreamClientNoTags())
    async with httpx.AsyncClient(app=app, base_url="http://test") as client:
        payload = {
            "model": "reasoning-llm",
            "stream": True,
            "messages": [{"role": "user", "content": "hi"}],
        }
        events = await _collect_events(client, payload)

    output_text = "".join(
        data["text"] for event, data in events if event == "output.delta"
    )
    assert output_text == "Hello world!"
