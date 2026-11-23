"""Compare the Python app against the TypeScript base app over HTTP.

Start both servers on different ports, then run:

    uv run python scripts/parity_check.py --ts http://127.0.0.1:8790 --py http://127.0.0.1:8788

Deterministic endpoints must match exactly. Chat answers come from an LLM, so
they are compared on shape and behavior (tools used, traceMeta, numbered steps),
not on exact wording.
"""

import argparse
import json
import re
import sys
import urllib.error
import urllib.request

CHAT_QUESTIONS = [
    "How do I turn Bluetooth on on my iPhone?",
    "How do I take a photo and send it on WhatsApp?",
    "How do I reconnect my iPhone to Wi-Fi?",
    "How do I find directions to a bus stop in Maps?",
]

INVALID_PAYLOADS = {
    "empty messages": {"sessionId": "parity", "messages": []},
    "missing sessionId": {"messages": [{"id": "1", "role": "user", "content": "hi", "timestamp": "t"}]},
    "empty sessionId": {"sessionId": "", "messages": [{"id": "1", "role": "user", "content": "hi", "timestamp": "t"}]},
    "bad role": {"sessionId": "parity", "messages": [{"id": "1", "role": "system", "content": "hi", "timestamp": "t"}]},
    "empty content": {"sessionId": "parity", "messages": [{"id": "1", "role": "user", "content": "", "timestamp": "t"}]},
}


def request(base: str, path: str, payload: dict | None = None) -> tuple[int, str]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(base + path, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()


def chat_payload(question: str) -> dict:
    return {
        "sessionId": "parity-session",
        "userId": "parity",
        "messages": [{"id": "m1", "role": "user", "content": question, "timestamp": "2026-01-01T00:00:00Z"}],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ts", default="http://127.0.0.1:8790", help="TypeScript base app URL")
    parser.add_argument("--py", default="http://127.0.0.1:8788", help="Python app URL")
    args = parser.parse_args()

    failures = 0

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        failures += 0 if ok else 1
        print(f"{'PASS' if ok else 'FAIL'}  {label}{f'  ({detail})' if detail else ''}")

    for path in ["/api/health", "/api/support-context"]:
        ts_status, ts_body = request(args.ts, path)
        py_status, py_body = request(args.py, path)
        check(f"GET {path} identical", (ts_status, json.loads(ts_body)) == (py_status, json.loads(py_body)))

    for label, payload in INVALID_PAYLOADS.items():
        ts_status, _ = request(args.ts, "/api/chat", payload)
        py_status, _ = request(args.py, "/api/chat", payload)
        check(f"POST /api/chat invalid: {label}", ts_status == py_status == 400, f"ts={ts_status} py={py_status}")

    ts_status, ts_body = request(args.ts, "/some/client/route")
    py_status, py_body = request(args.py, "/some/client/route")
    check("unknown route -> index.html", ts_status == py_status == 200 and "<html" in ts_body and "<html" in py_body)

    for question in CHAT_QUESTIONS:
        results = {}
        for name, base in [("ts", args.ts), ("py", args.py)]:
            status, body = request(base, "/api/chat", chat_payload(question))
            results[name] = json.loads(body) if status == 200 else {"error": status, "body": body}
        ts, py = results["ts"], results["py"]
        print(f"\n--- {question}")
        if "error" in ts or "error" in py:
            check("both answered", False, f"ts={ts.get('error')} py={py.get('error')}")
            continue
        check("response keys", set(ts) == set(py), f"{sorted(py)}")
        check("traceMeta", ts["traceMeta"] == py["traceMeta"], json.dumps(py["traceMeta"]))
        check("usedTools", ts["usedTools"] == py["usedTools"], f"ts={ts['usedTools']} py={py['usedTools']}")
        numbered = re.compile(r"^\s*1\.", re.MULTILINE)
        check(
            "numbered steps",
            bool(numbered.search(ts["answer"])) and bool(numbered.search(py["answer"])),
        )
        print(f"  ts answer: {ts['answer'][:140]!r}...")
        print(f"  py answer: {py['answer'][:140]!r}...")

    print(f"\n{'ALL CHECKS PASSED' if failures == 0 else f'{failures} CHECK(S) FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
