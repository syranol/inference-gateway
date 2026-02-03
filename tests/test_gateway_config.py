import httpx
import pytest

from app.gateway import create_app


class RecordingUpstreamClient:
    def __init__(self):
        self.complete_models = []
        self.stream_models = []
        self.reasoning_payloads = []

    async def complete(self, payload):
        self.complete_models.append(payload.get("model"))
        messages = payload.get("messages", [])
        if messages and "Reasoning:\n" in messages[1]["content"]:
            self.reasoning_payloads.append(messages[1]["content"])
        return "SUMMARY"

    async def stream_deltas(self, payload):
        self.stream_models.append(payload.get("model"))
        text = "<analysis>ABCDEFGHIJ</analysis><final>Answer.</final>"
        for chunk in [text[:10], text[10:20], text[20:]]:
            yield None, chunk


@pytest.mark.asyncio
async def test_allow_models_rejects(monkeypatch):
    monkeypatch.setenv("ALLOW_MODELS", "allowed")
    app = create_app(upstream_client=RecordingUpstreamClient())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "model": "blocked",
            "stream": True,
            "messages": [{"role": "user", "content": "hi"}],
        }
        resp = await client.post("/v1/chat/completions", json=payload)
        assert resp.status_code == 400
        assert resp.json()["detail"] == "Model not allowed"


@pytest.mark.asyncio
async def test_summary_model_default_used(monkeypatch):
    monkeypatch.setenv("SUMMARY_MODEL_DEFAULT", "summary-model")
    client_stub = RecordingUpstreamClient()
    app = create_app(upstream_client=client_stub)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "model": "main-model",
            "stream": True,
            "messages": [{"role": "user", "content": "hi"}],
        }
        async with client.stream("POST", "/v1/chat/completions", json=payload) as resp:
            assert resp.status_code == 200
            async for _ in resp.aiter_lines():
                pass

    assert client_stub.stream_models == ["main-model"]
    assert client_stub.complete_models
    assert all(model == "summary-model" for model in client_stub.complete_models)


@pytest.mark.asyncio
async def test_max_reasoning_chars(monkeypatch):
    monkeypatch.setenv("MAX_REASONING_CHARS", "5")
    client_stub = RecordingUpstreamClient()
    app = create_app(upstream_client=client_stub)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "model": "main-model",
            "stream": True,
            "messages": [{"role": "user", "content": "hi"}],
        }
        async with client.stream("POST", "/v1/chat/completions", json=payload) as resp:
            assert resp.status_code == 200
            async for _ in resp.aiter_lines():
                pass

    assert client_stub.reasoning_payloads
    reasoning_content = client_stub.reasoning_payloads[0]
    truncated = reasoning_content.split("Reasoning:\n", 1)[1]
    assert len(truncated) <= 5
