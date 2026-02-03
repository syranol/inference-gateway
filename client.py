from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

import httpx


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gateway SSE client")
    parser.add_argument("--url", default="http://localhost:8000/v1/chat/completions")
    parser.add_argument(
        "--model",
        default="meta-llama-3.1-8b-instruct",
        help="Model or endpoint ID. Optional if FRIENDLI_ENDPOINT_ID is set and --wake is used.",
    )
    parser.add_argument(
        "--message",
        default="Explain what FriendliAI does and what makes it special.",
        help="User message to send.",
    )
    parser.add_argument(
        "--wake",
        action="store_true",
        help="For Friendli Dedicated: wake endpoint and wait until it is running.",
    )
    parser.add_argument(
        "--friendli-endpoint-id",
        default=None,
        help="Dedicated endpoint ID (falls back to FRIENDLI_ENDPOINT_ID env var).",
    )
    parser.add_argument(
        "--wake-timeout",
        type=int,
        default=120,
        help="Max seconds to wait for Dedicated endpoint to be running.",
    )
    parser.add_argument(
        "--wake-interval",
        type=int,
        default=5,
        help="Polling interval in seconds for Dedicated endpoint status.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print the request payload before sending.",
    )
    return parser.parse_args()


def _handle_event(event: str, data: dict[str, Any]) -> None:
    if event == "summary.prompt":
        print("\n=== 1) Summary of the prompt ===\n" + data.get("text", ""))
    elif event == "summary.reasoning":
        print("\n=== 2) Summary of the model's reasoning ===\n" + data.get("text", ""))
    elif event == "output.delta":
        if not getattr(_handle_event, "_final_started", False):
            print("\n=== 3) The model's final output ===")
            _handle_event._final_started = True  # type: ignore[attr-defined]
        sys.stdout.write(data.get("text", ""))
        sys.stdout.flush()
    elif event == "output.done":
        print("\n\n[done]")
    elif event == "error":
        print(f"\n[error] {data}")


def _dedicated_status(endpoint_id: str, token: str) -> dict[str, Any] | None:
    url = f"https://api.friendli.ai/dedicated/beta/endpoint/{endpoint_id}/status"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = httpx.get(url, headers=headers, timeout=10.0)
        if resp.status_code >= 400:
            print(f"[warn] status check failed: {resp.status_code} {resp.text}")
            return None
        return resp.json()
    except Exception as exc:
        print(f"[warn] status check failed: {exc}")
        return None


def _dedicated_wake(endpoint_id: str, token: str) -> None:
    url = f"https://api.friendli.ai/dedicated/beta/endpoint/{endpoint_id}/wake"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = httpx.put(url, headers=headers, timeout=10.0)
        if resp.status_code >= 400:
            print(f"[warn] wake request failed: {resp.status_code} {resp.text}")
    except Exception as exc:
        print(f"[warn] wake request failed: {exc}")


def _is_running(status_payload: dict[str, Any]) -> bool:
    for key in ("status", "phase", "state"):
        if key in status_payload:
            value = str(status_payload[key]).upper()
            return value in {"RUNNING", "READY", "AVAILABLE"}
    return False


def _maybe_wake_dedicated(args: argparse.Namespace) -> None:
    endpoint_id = args.friendli_endpoint_id or os.getenv("FRIENDLI_ENDPOINT_ID")
    token = os.getenv("UPSTREAM_API_KEY")
    if not endpoint_id or not token:
        print("[warn] --wake set but FRIENDLI_ENDPOINT_ID or UPSTREAM_API_KEY not provided")
        return

    print(f"[info] checking dedicated endpoint status: {endpoint_id}")
    status = _dedicated_status(endpoint_id, token)
    if status and _is_running(status):
        print("[info] dedicated endpoint is already RUNNING")
        return

    print("[info] dedicated endpoint not ready; sending wake request")
    _dedicated_wake(endpoint_id, token)
    deadline = time.time() + args.wake_timeout
    while time.time() < deadline:
        time.sleep(args.wake_interval)
        status = _dedicated_status(endpoint_id, token)
        if status and _is_running(status):
            print("[info] dedicated endpoint is RUNNING")
            return
    print("[warn] dedicated endpoint did not reach RUNNING state before timeout")


def main() -> None:
    args = _parse_args()
    endpoint_id_env = os.getenv("FRIENDLI_ENDPOINT_ID")
    if args.model == "meta-llama-3.1-8b-instruct" and endpoint_id_env:
        args.model = endpoint_id_env
    if args.wake:
        print(f"[info] using model: {args.model}")
        _maybe_wake_dedicated(args)

    payload = {
        "model": args.model,
        "stream": True,
        "messages": [
            {"role": "user", "content": args.message},
        ],
    }
    if args.debug:
        print(f"[debug] url={args.url}")
        print(f"[debug] payload={json.dumps(payload, ensure_ascii=False)}")

    with httpx.Client(timeout=None) as client:
        with client.stream("POST", args.url, json=payload) as resp:
            if resp.status_code >= 400:
                print(resp.text)
                raise SystemExit(1)

            event = None
            for line in resp.iter_lines():
                if not line:
                    event = None
                    continue
                if line.startswith("event:"):
                    event = line[len("event:") :].strip()
                elif line.startswith("data:"):
                    data = json.loads(line[len("data:") :].strip())
                    _handle_event(event or "message", data)


if __name__ == "__main__":
    main()
