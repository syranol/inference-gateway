# Inference Gateway

## Overview
This project implements a Python 3.11+ gateway that fronts an existing `/chat/completions` API
and returns an SSE stream that always emits, in order:
1) Summary of the prompt
2) Summary of the model's reasoning
3) The model's final output

The design emphasizes low TTFT, failure resilience, and a stable developer-facing contract.

## Requirements
### Functional
- Accept `/chat/completions`-style requests and forward to upstream.
- Emit SSE in strict order: prompt summary → reasoning summary → final output.
- Support multiple reasoning-capable models via `model` (with optional `summary_model`).
- Provide a client script that consumes the SSE stream.
- Handle missing/malformed reasoning boundaries per documented assumptions.

### Non-functional
- Low TTFT (prompt summary should arrive quickly).
- Failure resilience (timeouts, retries for summary calls, graceful error events).
- Developer experience (clear event schema, predictable API surface).
- End-user experience (readable summaries, stable streaming behavior).
- Maintainability (clear assumptions, capability registry).

## Core entities
- **GatewayRequest**: inbound request; fields include `model`, `messages`, `stream`,
  `summary_model`, `temperature`, `max_tokens`.
- **UpstreamRequest**: request forwarded to `/chat/completions`, with injected system
  instructions to enforce `<analysis>`/`<final>` tags.
- **UpstreamStreamChunk**: streamed delta data from upstream.
- **SummaryTask**: non-streaming request for prompt or reasoning summaries.
- **GatewayEvent**: SSE events emitted by the gateway (`summary.prompt`, `summary.reasoning`,
  `output.delta`, `output.done`, `error`).
- **ModelCapability**: per-model metadata (tag format, reasoning support, parsing strategy).
- **RequestContext**: in-flight state (buffers, timers, request IDs, error state).

## API design
**Endpoint**: `POST /v1/chat/completions` (OpenAI-compatible shape with optional extensions)
**Gateway health**: `GET /healthz` (process liveness)
**Upstream health**: `GET /upstream-health` (checks upstream reachability)

**Request body (example):**
```json
{
  "model": "reasoning-llm",
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Explain why the sky is blue."}
  ],
  "stream": true,
  "summary_model": "fast-llm",
  "temperature": 0.2
}
```

**Response (SSE events):**
```
event: summary.prompt
data: {"text":"...","request_id":"..."}

event: summary.reasoning
data: {"text":"...","request_id":"..."}

event: output.delta
data: {"text":"...","request_id":"..."}

event: output.done
data: {"request_id":"..."}
```

## High-level flow
```
Client
  |
  |  POST /v1/chat/completions (stream=true)
  v
Gateway
  |-- Call A: prompt summary (fast, non-streaming)
  |-- Call B: upstream stream (tagged analysis/final)
  |-- Call C: reasoning summary (fast, non-streaming)
  |
  +--> SSE: summary.prompt -> summary.reasoning -> output.delta -> output.done
```

## Reasoning separation strategy
- Enforce `<analysis>...</analysis>` and `<final>...</final>` boundaries via a system prompt.
- If upstream provides explicit reasoning fields (e.g., `reasoning_content`), use them when
  `ENABLE_PARSE_REASONING=true`; otherwise fall back to tag parsing.

### Assumptions
- Missing `<analysis>` → empty reasoning summary; treat stream as final output.
- Missing `<final>` → treat remaining stream as reasoning; final output may be empty.

## Failure handling
- Timeouts + retries with backoff for summary calls (prompt + reasoning).
- If reasoning summary fails, continue streaming final output and emit an `error` event.
- If upstream streaming fails, emit an `error` event with partial state and close cleanly.
- On client disconnect, cancel upstream stream immediately.

## Multi-model support
- Pass through `model` from client request.
- Optional `summary_model` override for prompt/reasoning summaries.
- Allowlist controls via `ALLOW_MODELS`.

## Alternative approaches (tradeoffs)
- **Inline heuristics**: no prompt changes, but unreliable across models.
- **Schema-first prompting**: deterministic parsing but can drift and break streaming.
- **Single-call only**: lower cost, but harder to satisfy ordering + low TTFT.

## Implementation components
- FastAPI gateway with SSE streaming and upstream forwarding.
- Tag parser + buffering to preserve required ordering.
- Mock upstream server for local testing and env-based config for real endpoints.
- Client script that consumes SSE events and prints sections in order.
- Tests covering ordered output and missing-tag fallback.

## Setup
```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run locally (mock upstream)
The local demo uses three processes because the client talks to the gateway, and the gateway
forwards to the upstream mock. All three must be running to see the expected output.

Step-by-step:
1) Start the mock upstream.
2) Start the gateway (it calls upstream for summaries + streaming).
3) Run the client (prints SSE events in order).

Terminal 1:
```bash
source .venv/bin/activate
make mock-upstream
```

Terminal 2:
```bash
source .venv/bin/activate
make run-gateway
```

Terminal 3:
```bash
source .venv/bin/activate
make run-client
```

## Expected output (client)
```
Prompt summary:
Summary: system: You are a concise assistant... user: Explain why the sky is blue.

Reasoning summary:
Summary: Reasoning: We need to answer the user's question...

The sky is blue because shorter blue wavelengths are scattered more by the atmosphere,
making blue light reach our eyes from many directions.

[done]
```

## Run with a real upstream endpoint
```bash
export UPSTREAM_BASE_URL="https://your-upstream-host"
export UPSTREAM_PATH="/chat/completions"
export UPSTREAM_API_KEY="YOUR_KEY"
make run-gateway
```

Then call the gateway:
```bash
python3.11 client.py --url http://localhost:8000/v1/chat/completions --model reasoning-llm
```

## Testing
```bash
make test
```

## Gateway health check
```bash
make health-gateway
```

## Upstream health check
```bash
make health-upstream
```

## Development
1) Start mock upstream:
```bash
make mock-upstream
```

2) Run the gateway with auto-reload:
```bash
make run-gateway-dev
```

3) Send a request:
```bash
python3.11 client.py --url http://localhost:8000/v1/chat/completions
```

## Configuration (env vars)
- `UPSTREAM_BASE_URL` (default: `http://localhost:8001`)
- `UPSTREAM_PATH` (default: `/chat/completions`)
- `UPSTREAM_API_KEY` (optional)
- `SUMMARY_MODEL_DEFAULT` (optional)
- `ALLOW_MODELS` (comma-separated allowlist)
- `REQUEST_TIMEOUT` (seconds, default: 60)
- `SUMMARY_TIMEOUT` (seconds, default: 10)
- `MAX_REASONING_CHARS` (default: 8000)
- `ENABLE_PARSE_REASONING` (default: true; use upstream reasoning fields if present)

## AI Assistance
This work was developed with the help of an AI coding tool as a research, brainstorming,
and review aid (not as an autonomous code generator). Specifically, I used AI to:
- Brainstorm design options and weigh pros/cons (e.g., tag parsing vs heuristics, single-call
  vs dual-call pipelines, buffering strategies).
- Identify and close knowledge gaps (e.g., streaming SSE framing, TTFT tradeoffs, and
  reasoning separation patterns).
- Stress-test assumptions and failure modes before implementation.
- Assist with implementation planning and code scaffolding (gateway server, client script,
  parser/state machine, and test harness) while I review and integrate all changes.

All architectural decisions and the final written design were made, reviewed, and refined by me.
