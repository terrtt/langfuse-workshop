---
title: "Workshop (Python): Tracing an LLM Agent with Langfuse"
description: "Instrument the Python support agent so one chat turn becomes a nested Langfuse trace with OpenAI generations, an agent observation, and tool calls."
---

# 02 Tracing (Python)

> This is the Python version of [`docs/learner/02-tracing.md`](../../docs/learner/02-tracing.md).
> The goal and the resulting trace are the same, and the screenshots come from
> the shared lesson.

## Starting point

```bash
git checkout checkpoint/py-01-base-app
cd python
make setup
```

Start from the base app, which has no Langfuse wiring yet. The `langfuse` package
is already in `pyproject.toml`, so `make setup` installs it. Make sure the
repo-root `.env` has `OPENAI_API_KEY`, `LANGFUSE_PUBLIC_KEY`,
`LANGFUSE_SECRET_KEY`, and `LANGFUSE_BASE_URL`.

> On the Python track, `checkpoint/py-02-tracing` holds the **finished** result
> of this chapter. If you get stuck, compare your files with that tag, or check it
> out and continue.

## Why we trace

Tracing logs every step your agent takes: every model call, every tool call, and
the inputs and outputs of each, in order. It turns the agent from a black box into
something you can open up afterwards. When an answer is wrong, you can point at
the exact step where it went wrong instead of guessing.

For the bigger picture, see the
[Langfuse Academy lesson on tracing](https://langfuse.com/academy/tracing). For SDK
details, see the [tracing docs](https://langfuse.com/docs/tracing).

## Goal

When Dad asks "How do I turn Bluetooth on?", the agent calls OpenAI more than once.
It asks OpenAI what to do, calls `get_support_context` for Dad's iPhone setup,
asks OpenAI again, calls `search_help_library` for the Bluetooth steps, then asks
OpenAI once more for the numbered answer. None of that is visible today.

By the end of this chapter, one chat turn becomes one nested Langfuse trace that
shows the agent run, the OpenAI generations, and both tool calls in order.

![Spec's step by step process](../../docs/images/tracing/process_illustration.png)

We build the trace in three steps that mirror the agent's structure:

1. **First trace:** log the OpenAI generations.
2. **Nested traces:** group the generations under one agent run per turn.
3. **Recording tool calls:** make each tool call its own observation.

### TypeScript to Python at a glance

| TypeScript | Python (Langfuse SDK v5) |
| --- | --- |
| `new NodeSDK({ spanProcessors: [new LangfuseSpanProcessor()] }).start()` | `Langfuse(public_key=..., secret_key=..., base_url=...)`. The Python SDK is built on OpenTelemetry, so creating the client starts the export. |
| `observeOpenAI(new OpenAI())` | `from langfuse.openai import OpenAI` |
| `observe(fn, { name, asType: "agent" })` | `@observe(name=..., as_type="agent")` |
| `propagateAttributes({ userId, sessionId, tags }, fn)` | `with propagate_attributes(user_id=..., session_id=..., tags=...):` |
| `forceFlush()` + `sdk.shutdown()` | `get_client().flush()` + `get_client().shutdown()` |

## Step 1: First trace

We want to see the OpenAI calls themselves: their inputs and outputs, and how much
cost, tokens, and time each one takes.

### `app/tracing.py` (new file)

Create the Langfuse client once at startup, and flush it on shutdown:

```python
"""Langfuse tracing setup."""

import logging

from langfuse import Langfuse, get_client

from .env import env, is_langfuse_configured

logger = logging.getLogger("dad-it-support")


def init_tracing() -> None:
    if not is_langfuse_configured():
        logger.warning(
            "LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY are not set. "
            "Tracing is disabled; the app still answers."
        )
        # Without keys the SDK repeats its own auth warning on every traced call.
        logging.getLogger("langfuse").setLevel(logging.ERROR)
        return

    Langfuse(
        public_key=env.langfuse_public_key,
        secret_key=env.langfuse_secret_key,
        base_url=env.langfuse_base_url,
    )


def shutdown_tracing() -> None:
    if not is_langfuse_configured():
        return
    # Send whatever is still queued, so the last trace is not lost on Ctrl+C.
    client = get_client()
    client.flush()
    client.shutdown()
```

The client batches finished spans and uploads them in the background, so tracing
never delays Dad's answer. Without keys, the app logs one warning and keeps
answering, untraced.

### `app/server.py`

**Add the imports** at the top:

```python
from contextlib import asynccontextmanager

from .env import CLIENT_DIST, env, is_langfuse_configured   # add is_langfuse_configured
from .tracing import init_tracing, shutdown_tracing
```

**Replace** `app = FastAPI(title="Dad IT Support Agent")` with a lifespan that
starts tracing and flushes it on shutdown:

```python
@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_tracing()
    yield
    shutdown_tracing()


app = FastAPI(title="Dad IT Support Agent", lifespan=lifespan)
```

**In `health()`**, report whether tracing is configured:

```python
return {"ok": True, "provider": "openai", "tracingConfigured": is_langfuse_configured()}
```

### `app/support_agent.py`

Swap one import. Find:

```python
from openai import OpenAI
```

and change it to:

```python
from langfuse.openai import OpenAI
```

That's the whole change for this file. `langfuse.openai.OpenAI` is a drop-in
replacement for the official client, so every
`client.chat.completions.create(...)` call now records a generation.

**Verify:** restart `make app`, ask one question, and refresh Langfuse. You should
see one generation per OpenAI call, with prompt, response, tokens, and latency.
The generations are still flat: nothing groups them under one agent run, and the
trace has no meaningful name or input/output yet. Step 2 fixes that.

> **Python difference:** in the TypeScript lesson, each generation shows up as its
> own separate trace, as in the screenshot below. On the Python track, the
> generations from one chat turn already share **one trace**, listed side by side
> as top-level `OpenAI-generation` observations. FastAPI opens its own
> OpenTelemetry span for each request. Langfuse drops that span, but the
> generations keep its trace ID. You should still see three generations per
> Bluetooth question, just inside one trace.

![Langfuse Traces view after Step 1 (TypeScript track): each chat turn appears as standalone OpenAI generations.](../../docs/images/tracing/02-tracing-step-1.png)

## Step 2: Nested traces

To give the generations context, we group them under one agent run per turn. All
edits are in `app/support_agent.py`, and the loop itself doesn't change.

**1. Add the import:**

```python
from langfuse import get_client, observe
```

**2. Rename the existing function.** Find:

```python
def run_support_conversation(request: ChatRequest) -> ChatResponse:
```

and rename it to `_run_support_conversation_inner`. The body stays exactly the same:

```python
def _run_support_conversation_inner(request: ChatRequest) -> ChatResponse:
```

**3. Add the observed entry point at the bottom of the file:**

```python
TRACE_NAME = "dad-it-support-chat-turn"


@observe(name=TRACE_NAME, as_type="agent", capture_input=False, capture_output=False)
def run_support_conversation(request: ChatRequest) -> ChatResponse:
    langfuse = get_client()
    langfuse.update_current_span(input=request.model_dump(exclude_none=True))
    response = _run_support_conversation_inner(request)
    langfuse.update_current_span(output=response.model_dump())
    return response
```

`server.py` still imports `run_support_conversation` under the same name, so
nothing else changes.

> **Python difference:** by default, `@observe` records the input as
> `{"args": [...], "kwargs": {...}}`. The TS `observe` records the argument itself.
> `capture_input=False` plus `update_current_span(input=...)` keeps the root input
> as `{sessionId, userId, messages}` and the output as
> `{answer, usedTools, traceMeta}`, the same as TypeScript. Later chapters
> (monitoring, datasets) read these fields, so the shape matters.

**Verify:** one chat turn now shows up as a single `dad-it-support-chat-turn`
observation, with the OpenAI generations nested underneath.

![Trace tree after Step 2: one dad-it-support-chat-turn agent root with the OpenAI generations as children.](../../docs/images/tracing/02-tracing-step-2.png)

## Step 3: Recording tool calls

The generation output already lists the tool calls the model asked for, but
there's no observation for the tool run itself, so you can't see what went in and
what came out. Apply the same `@observe` pattern to each tool.

### `app/tools.py`

**Add the import:**

```python
from langfuse import get_client, observe
```

**Replace the existing `execute_tool`** with two observed helpers and a new
`execute_tool` that calls them. `TOOL_DEFINITIONS` stays untouched.

```python
# The tool takes no arguments, so skip the decorator's empty {"args": [], "kwargs": {}} input.
@observe(name="get_support_context", as_type="tool", capture_input=False)
def get_support_context_tool() -> dict[str, Any]:
    context = get_support_context()
    return {
        "ok": True,
        "context": {
            "id": context["id"],
            "label": context["label"],
            "devices": context["devices"],
            "deviceSummary": context["deviceSummary"],
            "responseStyle": context["responseStyle"],
            "scopeHighlights": context["scopeHighlights"],
            "notableApps": context["notableApps"],
        },
    }


# Record the input as {"question": ...}, matching the TS trace.
@observe(name="search_help_library", as_type="tool", capture_input=False)
def search_help_library_tool(question: str) -> dict[str, Any]:
    get_client().update_current_span(input={"question": question})
    guides = search_guides(question)
    return {
        "ok": True,
        "results": [
            {
                "id": guide["id"],
                "title": guide["title"],
                "summary": guide["summary"],
                "steps": guide["steps"],
                "caution": guide.get("caution"),
            }
            for guide in guides
        ],
    }


def execute_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "get_support_context":
        return get_support_context_tool()

    if name == "search_help_library":
        question = args.get("question")
        return search_help_library_tool("" if question is None else str(question))

    return {"ok": False, "error": f"Unsupported tool: {name}"}
```

If both versions of `execute_tool` stay in the file, Python silently uses the one
defined last. Delete the old one.

![Full trace after Step 3: dad-it-support-chat-turn (agent) with the OpenAI generations and the get_support_context and search_help_library tool observations underneath.](../../docs/images/tracing/02-tracing-step-3.png)

## How to verify you are done

- A single user turn creates one trace in Langfuse.
- The root observation is `dad-it-support-chat-turn`, of type `agent`.
- Child generations from `langfuse.openai`, each with prompt, response, tokens,
  and latency.
- Child tool observations `get_support_context` and `search_help_library`.
- The root input is the chat request, and the root output is the chat response.

To check all of this automatically, first add the
[user and session IDs bonus](#appendixbonus-section-user-and-session-ids) below,
then run:

```bash
make api              # terminal 1
make verify-tracing   # terminal 2
```

`scripts/verify_tracing.py` sends one chat turn, reads the trace back from
Langfuse, and checks the shape. It also starts a second server without Langfuse
keys (port 8799) to confirm the app still answers with exactly one warning.

> The script finds the trace by its session ID, so it needs the bonus code. Without
> it, the script stops at `FAIL  one chat turn creates exactly one trace
> (traces=0)` and runs none of the other checks. Until you add the bonus, check
> Steps 1–3 by eye in the Langfuse UI.

## Wrap-up

It's one pattern with different observation types. `@observe(as_type=...)` wraps
a function and records a span with the name and type you give it.
`langfuse.openai.OpenAI` does the same for every OpenAI call.

The [**Langfuse skill**](https://github.com/langfuse/skills) (`/langfuse`) applies
these patterns to a codebase for you. This walkthrough shows what it does under
the hood. For other SDKs (Anthropic, LangChain, LlamaIndex, plain HTTP), the
Langfuse [integrations catalogue](https://langfuse.com/integrations) has the
matching Python wrapper.

## Appendix/Bonus section: User and session IDs

The next thing most teams want is to **slice traces by user and by session**, for
example "every turn this user has had" or "the whole conversation from yesterday
morning". The `checkpoint/py-02-tracing` code includes this, so later chapters can
use the Users and Sessions views. See [Sessions](https://langfuse.com/docs/observability/features/sessions)
and [Users](https://langfuse.com/docs/observability/features/users) in the
Langfuse docs.

In `app/support_agent.py`, wrap the inner call in `propagate_attributes`:

```python
from langfuse import get_client, observe, propagate_attributes

TRACE_NAME = "dad-it-support-chat-turn"
TRACE_TAGS = ["langfuse-workshop", "dad-it-support"]


@observe(name=TRACE_NAME, as_type="agent", capture_input=False, capture_output=False)
def run_support_conversation(request: ChatRequest) -> ChatResponse:
    langfuse = get_client()
    langfuse.update_current_span(input=request.model_dump(exclude_none=True))

    context = get_support_context()
    with propagate_attributes(
        user_id=request.userId or f"workshop-{context['id']}",
        session_id=request.sessionId,
        trace_name=TRACE_NAME,
        tags=TRACE_TAGS,
    ):
        response = _run_support_conversation_inner(request)

    langfuse.update_current_span(output=response.model_dump())
    return response
```

Every observation created inside the `with` block, including the generations and
tool calls, gets the user ID, session ID, trace name, and tags. The Langfuse
**Users** view, **Sessions** view, and tag filters fill in as soon as the
attributes are present.

## Python-only notes

- **Restart after edits.** The Python server doesn't auto-reload. Press Ctrl+C,
  then run `make app` again.
- **A parent ID that points nowhere.** FastAPI opens its own OpenTelemetry span
  (`fastapi.endpoint`) for each request. Langfuse exports only Langfuse and GenAI
  spans, so it drops that span. The agent observation keeps a parent ID that
  points to it, but Langfuse still marks the agent as the root
  (`isRootObservation: true`). The trace tree looks the same as the TS one.
- **Traces take a few seconds to appear.** Spans upload in the background, and
  Langfuse needs a few seconds after that to process them. Refresh the UI.
- **Cost may show $0 through OpenRouter.** Langfuse prices by model name and may
  not know `openai/gpt-4.1-mini`. Tokens and latency are still recorded.

## End state

This finished traced app is the starting point for `03-prompt-management` and
`04-monitoring`.
