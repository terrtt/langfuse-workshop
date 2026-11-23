"""Check the Phase 2 (py-02-tracing) validation criteria against a running server and Langfuse.

With the server running (`make api`), run:

    uv run python scripts/verify_tracing.py --url http://127.0.0.1:8787

It sends one chat turn with a unique session id, reads the resulting observations
back from Langfuse, and checks the trace shape. Then it starts a second server with
the Langfuse keys removed and checks that it still answers and warns only once.
Skip that part with --skip-no-keys.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.env import env, is_langfuse_configured  # noqa: E402  (loads the root .env)

TRACE_NAME = "dad-it-support-chat-turn"
TRACE_TAGS = {"langfuse-workshop", "dad-it-support"}
NO_KEYS_PORT = 8799
NO_KEYS_WARNING = "Tracing is disabled"

# Starts the server as if LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY were absent from .env.
NO_KEYS_BOOTSTRAP = """
import dataclasses, os
import app.env as app_env
for key in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
    os.environ.pop(key, None)
app_env.env = dataclasses.replace(app_env.env, langfuse_public_key="", langfuse_secret_key="")
from app.server import main
main()
"""


def request(base: str, path: str, payload: dict | None = None) -> tuple[int, str]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(base + path, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()


def chat_payload(session_id: str, user_id: str) -> dict:
    return {
        "sessionId": session_id,
        "userId": user_id,
        "messages": [
            {
                "id": "m1",
                "role": "user",
                "content": "How do I turn Bluetooth on on my iPhone?",
                "timestamp": "2026-01-01T00:00:00Z",
            }
        ],
    }


def as_json(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def fetch_observations(session_id: str, timeout_s: int) -> list[dict]:
    from langfuse import Langfuse

    client = Langfuse(
        public_key=env.langfuse_public_key,
        secret_key=env.langfuse_secret_key,
        base_url=env.langfuse_base_url,
    )
    deadline = time.time() + timeout_s
    observations: list[dict] = []
    while time.time() < deadline:
        response = client.api.observations.get_many(
            session_id=session_id, fields="core,basic,io,trace_context", limit=100
        )
        observations = [item.dict() for item in response.data]
        # Ingestion is asynchronous: wait until the root and its final generation have landed.
        root = [o for o in observations if o["type"] == "AGENT"]
        if root and root[0].get("output") and sum(o["type"] == "GENERATION" for o in observations) >= 1:
            time.sleep(5)  # give late siblings a moment, then read once more
            response = client.api.observations.get_many(
                session_id=session_id, fields="core,basic,io,trace_context", limit=100
            )
            return [item.dict() for item in response.data]
        time.sleep(3)
    return observations


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=f"http://127.0.0.1:{env.port}", help="Running traced server")
    parser.add_argument("--timeout", type=int, default=90, help="Seconds to wait for Langfuse ingestion")
    parser.add_argument("--skip-no-keys", action="store_true", help="Skip the keys-removed check")
    args = parser.parse_args()

    failures = 0

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        failures += 0 if ok else 1
        print(f"{'PASS' if ok else 'FAIL'}  {label}{f'  ({detail})' if detail else ''}")

    if not is_langfuse_configured():
        print("LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY are not set in .env; nothing to verify.")
        return 1

    # 1. Health reports tracing when keys are present.
    status, body = request(args.url, "/api/health")
    check("GET /api/health tracingConfigured is true", status == 200 and json.loads(body).get("tracingConfigured") is True, body)

    # 2. One chat turn.
    session_id = f"py-verify-{uuid.uuid4().hex[:10]}"
    user_id = "py-verify-dad"
    status, body = request(args.url, "/api/chat", chat_payload(session_id, user_id))
    check("POST /api/chat answered", status == 200, f"status={status}")
    if status != 200:
        return 1
    used_tools = json.loads(body)["usedTools"]
    print(f"      session={session_id} usedTools={used_tools}")

    # 3. Read the trace back from Langfuse.
    print(f"      waiting up to {args.timeout}s for Langfuse ingestion...")
    observations = fetch_observations(session_id, args.timeout)
    trace_ids = {o["traceId"] for o in observations}
    check("one chat turn creates exactly one trace", len(trace_ids) == 1, f"traces={len(trace_ids)}")
    if len(trace_ids) != 1:
        return 1

    roots = [o for o in observations if o["type"] == "AGENT"]
    root = roots[0] if roots else {}
    check("root observation is an agent named dad-it-support-chat-turn",
          len(roots) == 1 and root.get("name") == TRACE_NAME and root.get("isRootObservation") is True)
    check("trace is named dad-it-support-chat-turn", root.get("traceName") == TRACE_NAME, str(root.get("traceName")))
    check("trace carries the langfuse-workshop / dad-it-support tags",
          TRACE_TAGS <= set(root.get("tags") or []), str(root.get("tags")))
    check("trace carries the user id", all(o.get("userId") == user_id for o in observations), user_id)
    check("trace carries the session id", all(o.get("sessionId") == session_id for o in observations), session_id)

    root_input, root_output = as_json(root.get("input")), as_json(root.get("output"))
    check("root input is the chat request with a messages array",
          isinstance(root_input, dict) and isinstance(root_input.get("messages"), list) and root_input["messages"])
    check("root output has the answer field",
          isinstance(root_output, dict) and bool(root_output.get("answer")))

    generations = [o for o in observations if o["type"] == "GENERATION"]
    check("trace contains generation observations under the agent",
          bool(generations) and all(g.get("parentObservationId") == root.get("id") for g in generations),
          f"generations={len(generations)}")
    check("generation input carries the message array",
          all(isinstance(as_json(g.get("input")), dict) and isinstance(as_json(g["input"]).get("messages"), list)
              for g in generations))

    # Every tool call the model requested should have its own tool observation.
    requested = []
    for generation in generations:
        output = as_json(generation.get("output"))
        if isinstance(output, dict):
            requested += [call["function"]["name"] for call in output.get("tool_calls") or []]
    tools = [o for o in observations if o["type"] == "TOOL"]
    check("one tool observation per tool call",
          sorted(o["name"] for o in tools) == sorted(requested),
          f"tool spans={sorted(o['name'] for o in tools)} tool calls={sorted(requested)}")
    check("tool observations are nested under the agent",
          bool(tools) and all(t.get("parentObservationId") == root.get("id") for t in tools))

    # 4. Keys removed: the app still answers and logs a single warning.
    if not args.skip_no_keys:
        python_dir = Path(__file__).resolve().parent.parent
        log_path = Path(tempfile.mkstemp(prefix="verify-no-keys-", suffix=".log")[1])
        with open(log_path, "w") as log:
            server = subprocess.Popen(
                [sys.executable, "-c", NO_KEYS_BOOTSTRAP],
                cwd=python_dir,
                env={**os.environ, "PORT": str(NO_KEYS_PORT)},
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        no_keys_url = f"http://127.0.0.1:{NO_KEYS_PORT}"
        try:
            for _ in range(60):
                try:
                    status, body = request(no_keys_url, "/api/health")
                    break
                except urllib.error.URLError:
                    time.sleep(0.5)
            check("keys removed: /api/health tracingConfigured is false",
                  json.loads(body).get("tracingConfigured") is False, body)
            answers = [request(no_keys_url, "/api/chat", chat_payload(f"{session_id}-nokeys", user_id))[0] for _ in range(2)]
            check("keys removed: the app still answers (2 turns)", answers == [200, 200], f"status={answers}")
        finally:
            server.terminate()
            server.wait(timeout=20)
        log_text = log_path.read_text()
        log_path.unlink(missing_ok=True)
        warnings = [line for line in log_text.splitlines() if "WARNING" in line or NO_KEYS_WARNING in line]
        check("keys removed: exactly one warning logged", len(warnings) == 1, f"warnings={warnings}")
        check("keys removed: no crash / traceback", "Traceback" not in log_text)

    print(f"\n{'ALL CHECKS PASSED' if failures == 0 else f'{failures} CHECK(S) FAILED'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
