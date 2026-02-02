# Q2 - Inference Gateway (Design)

## Overview
Design a Python 3.11+ gateway that fronts an existing `/chat/completions` API and returns an
SSE stream that always emits, in order:
1) Summary of the prompt
2) Summary of the model's reasoning
3) The model's final output

The design prioritizes low TTFT, failure resilience, and strong developer experience.

## Requirements
### Functional
- Accept `/chat/completions`-style requests and forward to upstream.
- Emit SSE stream in order: prompt summary → reasoning summary → final output.
- Support multiple reasoning-capable models via `model` (plus optional `summary_model`).
- Provide a client script that demonstrates consumption of the SSE stream.
- Handle missing/malformed reasoning boundaries per documented assumptions.

### Non-functional
- Low TTFT (prompt summary should arrive quickly).
- Failure resilience (timeouts, retries for summary calls, graceful error events).
- Developer experience (clear event schema, simple request surface).
- End-user experience (readable summaries, stable streaming behavior).
- Maintainability (clear assumptions, capability registry).

## Core entities (definitions)
Establishing the key entities helps reason about responsibilities and API shape.

- **GatewayRequest**: inbound request to the gateway. Likely fields: `model`, `messages`,
  `stream`, `summary_model`, `temperature`, `max_tokens`, `request_id` (optional).
- **UpstreamRequest**: request forwarded to `/chat/completions`, including injected system
  instructions to enforce `<analysis>`/`<final>` tags.
- **UpstreamStreamChunk**: streaming SSE chunk from upstream (delta content, metadata).
- **SummaryTask**: non-streaming request used for prompt summary or reasoning summary.
- **GatewayEvent**: SSE events emitted by the gateway (`summary.prompt`, `summary.reasoning`,
  `output.delta`, `output.done`, `error`).
- **ModelCapability**: per-model metadata (tag format, reasoning support, parsing strategy).
- **RequestContext**: in-flight state (buffers, timers, correlation IDs, error state).

## API design (gateway surface)
**Endpoint**: `POST /v1/chat/completions` (OpenAI-compatible shape, with optional extensions)

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

**Response (SSE stream events):**
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

## High-level flow (ASCII diagram)
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

## Recommended approach (hybrid, capability-first)
**Primary strategy:** enforce structured reasoning/output boundaries using a system prompt that
wraps reasoning in `<analysis>...</analysis>` and the final answer in `<final>...</final>`.

**Capability-first fallback:** if upstream chunks include explicit reasoning fields (e.g.,
`reasoning_content`), use them directly. Otherwise, fall back to tag parsing. This keeps the
solution robust without depending on upstream features the prompt says are absent.

**Low-TTFT ordering:** use a dual-call pipeline for summaries while streaming the main answer:

1) **Call A (non-streaming, fast)**: summarize the prompt and emit immediately.
2) **Call B (streaming)**: generate the actual answer with enforced tags; buffer reasoning tokens.
3) **Call C (non-streaming, fast)**: summarize the buffered reasoning. While this runs, buffer
   `<final>` tokens; once summary is ready, emit reasoning summary then flush final output and
   continue streaming new final tokens.

This preserves required ordering while minimizing latency.

## Assumptions (documented behavior)
- The gateway injects a system instruction enforcing `<analysis>`/`<final>` tags.
- If `<analysis>` is missing, the gateway emits an empty reasoning summary and treats all tokens
  as final output.
- If `<final>` is missing, the gateway treats the remaining stream as reasoning and may emit an
  empty final output.

## SSE event schema (suggested)
Use explicit event types for clarity and easy client integration:
- `summary.prompt` -> {"text": "...", "request_id": "..."}
- `summary.reasoning` -> {"text": "...", "request_id": "..."}
- `output.delta` -> {"text": "...", "request_id": "..."}
- `output.done` -> {"request_id": "..."}
- `error` -> {"message": "...", "stage": "...", "request_id": "..."}

## Failure resilience
- Timeouts + retries with backoff for Call A/C
- If reasoning summary fails, still stream final output and emit an `error` event
- If upstream streaming fails, emit an `error` event with partial state
- On client disconnect, cancel upstream stream immediately

## Risks & mitigations
- **Upstream does not distinguish reasoning vs output**: enforce `<analysis>`/`<final>` tags
  via system prompt; fall back to tag parsing or empty summaries if missing.
- **Ordering requirement delays output**: use dual-call pipeline and buffer final output until
  reasoning summary is ready.
- **Streaming failures mid-response**: emit structured SSE `error` events and close cleanly.
- **Model variance**: maintain a capability allowlist and default to safe parsing strategies.
- **No monkey-patching constraint**: keep all parsing and streaming logic in the gateway layer.

## Multi-model support
- Pass through `model` from client request
- Optional `summary_model` override for prompt/reasoning summaries
- Maintain a small allowlist with model capabilities (tag format, reasoning support)

## Alternative approaches (tradeoffs)
- **Inline validation / heuristics**: no prompt changes, but unreliable across models
- **Schema-first prompting**: deterministic parsing but can drift and break streaming
- **Dual-call only**: best latency, more moving parts and cost

## Next steps (implementation plan)
- FastAPI gateway with SSE streaming
- httpx for upstream streaming and retries
- Client script that prints sections in order
- Tests for ordering, missing tags, and upstream failure

## Requirements (expected)
- Python 3.11+
- HTTP client with streaming support (e.g., httpx)
- SSE response generation

## AI Assistance
This work was developed with the help of an AI coding tool as a research, brainstorming,
and review aid (not as an autonomous code generator). Specifically, I used AI to:
- Brainstorm design options and weigh pros/cons (e.g., tag parsing vs heuristics, single-call
  vs dual-call pipelines, buffering strategies).
- Identify and close knowledge gaps (e.g., streaming SSE framing, TTFT tradeoffs, and
  reasoning separation patterns).
- Stress-test assumptions and failure modes before implementation.
- Assist with implementation planning and code scaffolding (gateway server, client script,
  and test harness) while I review and integrate all changes.

All architectural decisions and the final written design were made, reviewed, and refined by me.

## Planned work (implementation)
- Build the FastAPI gateway with SSE streaming and upstream forwarding.
- Implement tag parsing, buffering, and summary orchestration (Call A/B/C).
- Add a mock upstream server plus env-based config for real endpoints.
- Provide a client script and tests (ordering, missing tags, upstream failure).
- Update README with run/test instructions and expected output.
