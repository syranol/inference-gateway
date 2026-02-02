from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import httpx


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gateway SSE client")
    parser.add_argument("--url", default="http://localhost:8000/v1/chat/completions")
    parser.add_argument("--model", default="reasoning-llm")
    parser.add_argument(
        "--message",
        default="Explain why the sky is blue.",
        help="User message to send.",
    )
    return parser.parse_args()


def _handle_event(event: str, data: dict[str, Any]) -> None:
    if event == "summary.prompt":
        print("\nPrompt summary:\n" + data.get("text", ""))
    elif event == "summary.reasoning":
        print("\nReasoning summary:\n" + data.get("text", ""))
    elif event == "output.delta":
        sys.stdout.write(data.get("text", ""))
        sys.stdout.flush()
    elif event == "output.done":
        print("\n\n[done]")
    elif event == "error":
        print(f"\n[error] {data}")


def main() -> None:
    args = _parse_args()

    payload = {
        "model": args.model,
        "stream": True,
        "messages": [
            {"role": "user", "content": args.message},
        ],
    }

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
