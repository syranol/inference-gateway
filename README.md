# Inference Gateway (SSE)

## I. Design
### Requirements
**Functional**
- Accept `/chat/completions`-style requests and forward to upstream.
- Emit SSE in strict order: prompt summary → reasoning summary → final output.
- Support multiple reasoning-capable models via `model` (with optional `summary_model`).
- Provide a client script that consumes the SSE stream.
- Handle missing/malformed reasoning boundaries per documented assumptions.

**Non-functional**
- Low TTFT (prompt summary should arrive quickly).
- Failure resilience (timeouts, retries for summary calls, graceful error events).
- Developer experience (clear event schema, predictable API surface).
- End-user experience (readable summaries, stable streaming behavior).
- Maintainability (clear assumptions, capability registry).

### Core entities
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

### API design
- **Endpoint**: `POST /v1/chat/completions` (OpenAI-compatible shape with optional extensions)
- **Gateway health**: `GET /healthz` (process liveness)
- **Upstream health**: `GET /upstream-health` (checks upstream reachability)

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

### Implementation components
- FastAPI gateway with SSE streaming and upstream forwarding.
- Tag parser + buffering to preserve required ordering.
- Mock upstream server for local testing and env-based config for real endpoints.
- Client script that consumes SSE events and prints sections in order.
- Tests covering ordered output, config behavior, and missing-tag fallback.

### High-level flow
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

## II. How to run / test
There are three ways to test this repository:
1) Mock upstream (local, no credentials required).
2) Friendli Dedicated endpoint (live API, requires endpoint ID + token).
3) Friendli Serverless quick test (live API, preconfigured model).

### Mock upstream (local)
**Setup**
```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Steps to run**
The local demo uses three processes because the client talks to the gateway, and the gateway
forwards to the upstream mock. All three must be running to see the expected output.

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

**Expected result (mock)**
```
=== 1) Summary of the prompt ===
...
=== 2) Summary of the model's reasoning ===
...
=== 3) The model's final output ===
...
[done]
```

### Dedicated (Friendli)
**Setup**
```bash
source .venv/bin/activate
export UPSTREAM_BASE_URL="https://api.friendli.ai/dedicated/v1"
export UPSTREAM_PATH="/chat/completions"
export UPSTREAM_API_KEY="YOUR_FRIENDLI_TOKEN"
```

**Steps to run**
```bash
make run-gateway
python3.11 client.py --url http://localhost:8000/v1/chat/completions --model YOUR_ENDPOINT_ID --wake
```

Tip: check Dedicated endpoint readiness first:
```bash
export FRIENDLI_ENDPOINT_ID="YOUR_ENDPOINT_ID"
make check-dedicated
```
If `--wake` fails, verify the Dedicated endpoint is not terminated (terminated endpoints must be redeployed).

**Expected result (dedicated)**
- Same ordered SSE sections as the mock run.
- Content varies based on model and prompt.

### Serverless (Friendli)
**Setup**
```bash
source .venv/bin/activate
export UPSTREAM_BASE_URL="https://api.friendli.ai/serverless/v1"
export UPSTREAM_PATH="/chat/completions"
export UPSTREAM_API_KEY="YOUR_FRIENDLI_TOKEN"
```

**Steps to run**
```bash
make run-gateway
python3.11 client.py --url http://localhost:8000/v1/chat/completions --model YOUR_SERVERLESS_MODEL
```

**Expected result (serverless)**
- Same ordered SSE sections as the mock run.
- Content varies based on model and prompt.

### Serverless quick test (Friendli)
This model is free until February 11, 2026:
`LGAI-EXAONE/K-EXAONE-236B-A23B`

**Setup**
```bash
source .venv/bin/activate
export UPSTREAM_BASE_URL="https://api.friendli.ai/serverless/v1"
export UPSTREAM_PATH="/chat/completions"
export UPSTREAM_API_KEY="YOUR_FRIENDLI_TOKEN"
```

**Steps to run**
```bash
make run-gateway
python3.11 client.py --url http://localhost:8000/v1/chat/completions --model LGAI-EXAONE/K-EXAONE-236B-A23B
```

**Expected result**
- Same ordered SSE sections as the mock run.
- Content varies based on model and prompt.

## III. How to execute tests
```bash
make test
```
Test coverage includes:
- Gateway ordering and missing-tag fallback behavior.
- Configuration defaults/overrides and model allowlist enforcement.
- Summary model selection and reasoning truncation behavior.

## IV. Configuration (env vars)
Set env vars in your shell before starting the gateway, for example:
```bash
export UPSTREAM_BASE_URL="https://api.friendli.ai/serverless/v1"
export UPSTREAM_PATH="/chat/completions"
export UPSTREAM_API_KEY="YOUR_FRIENDLI_TOKEN"
```

- `UPSTREAM_BASE_URL` (default: `http://localhost:8001`)
- `UPSTREAM_PATH` (default: `/chat/completions`)
- `UPSTREAM_API_KEY` (optional)
- `SUMMARY_MODEL_DEFAULT` (optional)
- `ALLOW_MODELS` (comma-separated allowlist)
- `REQUEST_TIMEOUT` (seconds, default: 60)
- `SUMMARY_TIMEOUT` (seconds, default: 10)
- `MAX_REASONING_CHARS` (default: 8000)
- `UPSTREAM_MAX_RETRIES` (default: 3)
- `UPSTREAM_RETRY_BACKOFF` (seconds, default: 1.0)
- `ENABLE_PARSE_REASONING` (default: true; use upstream reasoning fields if present)

## V. Makefile commands
- `make mock-upstream` — run local upstream mock
- `make run-gateway` — run gateway server
- `make run-gateway-dev` — run gateway with auto-reload
- `make run-client` — run client against gateway
- `make test` — run tests
- `make health-gateway` — check gateway liveness (`/healthz`)
- `make health-upstream` — check upstream reachability (`/upstream-health`)
- `make check-dedicated` — check Friendli Dedicated endpoint status

## VI. AI Assistance
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

## VII. Reasoning separation strategy
- Enforce `<analysis>...</analysis>` and `<final>...</final>` boundaries via a system prompt.
- If upstream provides explicit reasoning fields (e.g., `reasoning_content`), use them when
  `ENABLE_PARSE_REASONING=true`; otherwise fall back to tag parsing.

## VIII. Assumptions
- Missing `<analysis>` → empty reasoning summary; treat stream as final output.
- Missing `<final>` → treat remaining stream as reasoning; final output may be empty.

## IX. Failure handling
- Timeouts + retries with backoff for summary calls (prompt + reasoning) and initial upstream
  stream connection (retryable 5xx, e.g., 503 during warm-up).
- If reasoning summary fails, continue streaming final output and emit an `error` event.
- If upstream streaming fails, emit an `error` event with partial state and close cleanly.
- On client disconnect, cancel upstream stream immediately.

### Upstream retry policy
- Retries apply to upstream 5xx responses (502/503/504) and request errors.
- Defaults: `UPSTREAM_MAX_RETRIES=3`, `UPSTREAM_RETRY_BACKOFF=1.0` (exponential backoff).
- This is especially useful for Dedicated endpoints warming up (503).

## X. Multi-model support
- Pass through `model` from client request.
- Optional `summary_model` override for prompt/reasoning summaries.
- Allowlist controls via `ALLOW_MODELS`.

## XI. Alternative approaches (tradeoffs)
- **Inline heuristics**: no prompt changes, but unreliable across models.
- **Schema-first prompting**: deterministic parsing but can drift and break streaming.
- **Single-call only**: lower cost, but harder to satisfy ordering + low TTFT.
