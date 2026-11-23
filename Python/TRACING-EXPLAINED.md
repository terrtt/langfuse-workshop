# How tracing works in the Python app

This explains the Phase 2 (tracing) changes to the Python Dad IT Support Agent:
what each changed line does, what each parameter means, how data gets from the app
to Langfuse, and how many separate steps end up as **one** trace.

Line numbers refer to the files in `python/app/` as they are now.

---

## 1. The short version (for a manager)

- Every time Dad asks a question, the app now records **one trace** in Langfuse:
  a timeline of everything the agent did for that question.
- The trace contains one **agent** step (the whole turn), each **OpenAI call**
  (with prompt, answer, token counts, latency, and cost), and each **tool call**
  (with its input and output), nested in the order they happened.
- Five small code changes did this. No business logic changed: the agent answers
  exactly as before.
- Recording happens **in memory**, and uploading happens **in the background**
  every few seconds. Dad's answer is never slowed down by the upload, and if
  Langfuse is unreachable, the app still answers.
- It is built on **OpenTelemetry (OTel)**, the industry standard for tracing.
  Langfuse adds the LLM-specific parts on top: prompts, tokens, cost, and agent
  and tool types.
- If the Langfuse keys are missing, tracing switches off, the app logs one
  warning, and everything else keeps working.

---

## 2. Vocabulary

| Term | Meaning here |
| --- | --- |
| **Trace** | Everything that happened for one chat turn. Identified by a 32-character **trace ID**. |
| **Span** | One timed step inside a trace: start time, end time, input, output, and a pointer to its parent span. Identified by a 16-character **span ID**. This is the OpenTelemetry term. |
| **Observation** | Langfuse's name for a span. Same thing, with a **type** attached: `agent`, `generation`, `tool`, `span`, and so on. |
| **Generation** | An observation for one LLM call. Langfuse shows the model, prompt, response, token usage, and cost for it. |
| **OpenTelemetry (OTel)** | The open standard and libraries for creating spans and sending them somewhere. The Langfuse Python SDK is built on it. |
| **OTLP** | The OpenTelemetry Protocol, the wire format spans are uploaded in (HTTP + protobuf). |
| **Tracer provider** | The OTel object that creates spans and hands finished ones to processors. |
| **Span processor** | Code that runs when a span starts and ends. Langfuse's processor queues finished spans and uploads them in batches. |
| **Context** | OTel's record of "which span is active right now". New spans read it to find their parent. This is what makes nesting automatic. |

---

## 3. The whole pipeline in one picture

```
 ┌─────────────────────────────── Python process (FastAPI) ────────────────────────────────┐
 │                                                                                         │
 │  app startup ── init_tracing() ── Langfuse(...)                                         │
 │                                     ├─ creates an OTel TracerProvider                   │
 │                                     ├─ attaches LangfuseSpanProcessor (batching)        │
 │                                     └─ which owns an OTLPSpanExporter (HTTP uploader)   │
 │                                                                                         │
 │  POST /api/chat                                                                         │
 │   └─ run_support_conversation()     @observe(as_type="agent")  ── span A starts         │
 │        └─ propagate_attributes(user, session, name, tags)                               │
 │             └─ _run_support_conversation_inner()                                        │
 │                  ├─ client.chat.completions.create()   langfuse.openai ── span B (gen)   │
 │                  ├─ get_support_context_tool()         @observe(tool)  ── span C         │
 │                  ├─ client.chat.completions.create()                   ── span D (gen)   │
 │                  ├─ search_help_library_tool()         @observe(tool)  ── span E         │
 │                  └─ client.chat.completions.create()                   ── span F (gen)   │
 │        span A ends (after B–F)                                                          │
 │                                                                                         │
 │  every finished span ─► LangfuseSpanProcessor.on_end() ─► filter ─► in-memory queue     │
 │                                                                         │               │
 └─────────────────────────────────────────────────────────────────────────┼───────────────┘
                     background thread, every 5 s or every 512 spans, or on flush()
                                                                           ▼
                 HTTPS POST  {LANGFUSE_BASE_URL}/api/public/otel/v1/traces   (OTLP, Basic auth)
                                                                           ▼
                 Langfuse Cloud: groups spans by trace ID, links them by parent span ID,
                 computes cost from model + tokens, shows one trace tree in the UI
```

---

## 4. What changed, file by file

| File | Before (py-01) | After (py-02) |
| --- | --- | --- |
| `app/tracing.py` | did not exist | Creates the Langfuse client at startup and flushes it at shutdown |
| `app/server.py` | plain FastAPI app; health always said `tracingConfigured: false` | Starts and stops tracing with the app; health reports whether keys are set |
| `app/support_agent.py` | `from openai import OpenAI`; one function `run_support_conversation` | Langfuse's OpenAI client; the loop renamed to `_run_support_conversation_inner`; a new traced `run_support_conversation` wraps it |
| `app/tools.py` | `execute_tool` did the tool work inline | Each tool is its own traced function; `execute_tool` calls them |
| `app/env.py` | unchanged | Already loaded the Langfuse keys from `.env` in py-01 |

---

## 5. Line by line

### 5.1 `app/env.py`: where the keys come from (unchanged)

```python
14: load_dotenv(REPO_ROOT / ".env", override=True)
15: load_dotenv(PYTHON_ROOT / ".env", override=True)
```

- Reads the repo-root `.env`, then the optional `python/.env`, into the process
  environment (`os.environ`).
- `override=True` means values in the file win over values already exported in
  your shell.
- After this, `env.langfuse_public_key`, `env.langfuse_secret_key`, and
  `env.langfuse_base_url` hold the three settings tracing needs.

```python
51: def is_langfuse_configured() -> bool:
52:     return bool(env.langfuse_public_key and env.langfuse_secret_key)
```

- Returns `True` only if both keys are non-empty. The app uses it to decide
  whether to switch tracing on, and to fill `tracingConfigured` in `/api/health`.

### 5.2 `app/tracing.py`: the line that turns on export

```python
17: def init_tracing() -> None:
18:     if not is_langfuse_configured():
19:         logger.warning("LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY are not set. "
21:                        "Tracing is disabled; the app still answers.")
24:         logging.getLogger("langfuse").setLevel(logging.ERROR)
25:         return
```

- **Lines 18–25 (no keys):** log **one** warning and stop. No client is created,
  so nothing is ever sent.
- **Line 24:** without keys, the SDK would print its own "client is disabled"
  warning on **every** traced call. Raising the `langfuse` logger to `ERROR`
  silences those repeats but keeps real errors visible.

```python
28:     Langfuse(
29:         public_key=env.langfuse_public_key,
30:         secret_key=env.langfuse_secret_key,
31:         base_url=env.langfuse_base_url,
32:     )
```

**Lines 28–32 are the line that enables export to Langfuse.** Creating this one
object sets up the whole pipeline:

1. **A tracer provider.** If no OTel tracer provider exists yet, the SDK creates
   one and registers it as the process-wide (global) provider.
2. **`LangfuseSpanProcessor`**, attached to that provider. It is a subclass of
   OTel's standard `BatchSpanProcessor`.
3. **`OTLPSpanExporter`**, owned by the processor, pointed at
   `{base_url}/api/public/otel/v1/traces`.
4. **Registration of the client** as the default instance, so every later
   `get_client()`, `@observe`, `propagate_attributes`, and the OpenAI wrapper
   find it. The object doesn't need to be stored in a variable.

| Parameter | What it does |
| --- | --- |
| `public_key` (`pk-lf-...`) | Identifies your Langfuse **project**. Sent as the username in the `Authorization: Basic` header and as an `x-langfuse-public-key` header. The processor also uses it to drop spans that belong to a different project. |
| `secret_key` (`sk-lf-...`) | The password half of Basic auth. The SDK builds `Authorization: Basic base64(public_key:secret_key)` once. Never commit it. |
| `base_url` | Which Langfuse server to send to. Default `https://cloud.langfuse.com` (EU region). Spans go to `{base_url}/api/public/otel/v1/traces`. |

Parameters we **didn't** pass, and their defaults (all are options on `Langfuse(...)`):

| Parameter | Default | Meaning |
| --- | --- | --- |
| `flush_at` | 512 spans (OTel default) | Upload as soon as this many finished spans are queued. Env var `LANGFUSE_FLUSH_AT`. |
| `flush_interval` | 5 seconds (OTel default) | Upload at least this often. Env var `LANGFUSE_FLUSH_INTERVAL`. This is why traces appear a few seconds after a chat. |
| queue size | 2048 spans (OTel default) | Spans kept in memory waiting to upload. If Langfuse is down for a long time and the queue fills, new spans are dropped instead of using unlimited memory. |
| `sample_rate` | 1.0 | Fraction of traces to keep. `0.2` would keep 1 in 5. |
| `environment`, `release` | none | Labels such as `production` or a git SHA, for filtering in the UI. |
| `mask` | none | A function to scrub sensitive data (emails, card numbers) before upload. |
| `should_export_span` | Langfuse default filter | Decides which spans are uploaded. See section 9. |
| `tracing_enabled` | `True` | Master on/off switch. |

```python
35: def shutdown_tracing() -> None:
36:     if not is_langfuse_configured():
37:         return
39:     client = get_client()
40:     client.flush()
41:     client.shutdown()
```

- **Line 39, `get_client()`:** returns the client registered on line 28.
- **Line 40, `flush()`:** uploads everything still in the queue **now**, instead of
  waiting for the next 5-second tick. Without it, pressing Ctrl+C right after a
  chat could lose the last trace.
- **Line 41, `shutdown()`:** stops the background upload thread cleanly.

### 5.3 `app/server.py`: running it with the app

```python
19: @asynccontextmanager
20: async def lifespan(_app: FastAPI):
21:     init_tracing()
22:     yield
23:     shutdown_tracing()
26: app = FastAPI(title="Dad IT Support Agent", lifespan=lifespan)
```

- **`lifespan`** is FastAPI's hook for "run once at startup and once at shutdown".
  Code before `yield` runs when the server starts, and code after `yield` runs
  when it stops (Ctrl+C or SIGTERM).
- **Line 21:** tracing starts before the first request is served.
- **Line 23:** the last traces are flushed before the process exits.
- **Line 26:** `lifespan=lifespan` connects the hook to the app.

```python
37: return {"ok": True, "provider": "openai", "tracingConfigured": is_langfuse_configured()}
```

- `/api/health` now tells the UI (and you) whether tracing is on.

### 5.4 `app/support_agent.py`: OpenAI calls become generations

```python
10: from langfuse.openai import OpenAI
```

- This replaces `from openai import OpenAI`. `langfuse.openai.OpenAI` is the
  official OpenAI client. When `langfuse.openai` is imported, it **patches** the
  OpenAI SDK's `chat.completions.create` method (using the `wrapt` library),
  so every call goes through a small Langfuse wrapper.
- For each call, the wrapper:
  1. starts a **generation** observation named `OpenAI-generation`, as a child of
     whatever span is active right now;
  2. records the **input** (the `messages` array and the `tools` list), the
     **model** name, and **model parameters** such as `tool_choice`;
  3. calls the real OpenAI API;
  4. records the **output** (the assistant message, including any `tool_calls`),
     the **token usage** (prompt, completion, total), and the timing;
  5. ends the generation.
- Langfuse then calculates **cost** on the server from the model name and the
  token counts. Through OpenRouter the model name is `openai/gpt-4.1-mini`, which
  Langfuse may not have a price for, so cost can show $0 while tokens are correct.
- Line 99 (`client = OpenAI(api_key=...)`) and line 109 (`client.chat.completions.create(...)`)
  did **not** change. The import alone makes them traced.

```python
35: TRACE_NAME = "dad-it-support-chat-turn"
36: TRACE_TAGS = ["langfuse-workshop", "dad-it-support"]
```

- The name every chat-turn trace gets, and the tags used for filtering in the UI.

```python
97: def _run_support_conversation_inner(request: ChatRequest) -> ChatResponse:
```

- The original agent loop, renamed and otherwise **unchanged**. The leading `_`
  marks it as internal. Everything outside calls the traced wrapper below.

```python
164: @observe(name=TRACE_NAME, as_type="agent", capture_input=False, capture_output=False)
165: def run_support_conversation(request: ChatRequest) -> ChatResponse:
```

`@observe` is a **decorator**: it wraps the function so that every call opens a
span when the function starts and closes it when the function returns.

| Parameter | Value | What it does |
| --- | --- | --- |
| `name` | `"dad-it-support-chat-turn"` | The observation name shown in Langfuse. Without it, the function name is used. |
| `as_type` | `"agent"` | The observation type. Langfuse shows an agent icon and treats this as the root of the agent run. Other options: `span`, `generation`, `tool`, `chain`, `retriever`, `evaluator`, `guardrail`, `embedding`. |
| `capture_input` | `False` | Don't record the function arguments automatically. The Python default records them as `{"args": [...], "kwargs": {...}}`, which doesn't match the TS trace shape, so we set the input ourselves on line 167. |
| `capture_output` | `False` | Don't record the return value automatically. We set it ourselves on line 178. |

If the function raises an exception, `@observe` marks the observation
`level=ERROR` with the error message, ends it, and re-raises the exception.

```python
166:     langfuse = get_client()
167:     langfuse.update_current_span(input=request.model_dump(exclude_none=True))
```

- **`get_client()`:** returns the client created in `init_tracing()`.
- **`update_current_span(input=...)`:** writes the input onto the span that is
  active right now, which is the agent span `@observe` just opened.
- **`request.model_dump(exclude_none=True)`:** turns the Pydantic request into a
  plain dict, `{"sessionId": ..., "userId": ..., "messages": [...]}`, leaving out
  empty fields. This is the same shape the TS trace has, and later steps (the
  monitoring evaluators, datasets) read `messages` from it.

```python
170:     with propagate_attributes(
171:         user_id=request.userId or f"workshop-{context['id']}",
172:         session_id=request.sessionId,
173:         trace_name=TRACE_NAME,
174:         tags=TRACE_TAGS,
175:     ):
176:         response = _run_support_conversation_inner(request)
```

`propagate_attributes` attaches trace-level information to the current span
**and** to every span created inside the `with` block.

| Parameter | Value | Where it shows up in Langfuse |
| --- | --- | --- |
| `user_id` | the request's `userId`, or `workshop-dad-default` if the UI didn't send one | **Users** view: all traces for one user |
| `session_id` | the chat's `sessionId` from the UI | **Sessions** view: all turns of one conversation, in order |
| `trace_name` | `dad-it-support-chat-turn` | The trace name in the Traces list |
| `tags` | `langfuse-workshop`, `dad-it-support` | Tag filters in the Traces list |

It also accepts `metadata`, `version`, and `environment`. `as_baggage=True`
would carry these values across HTTP calls to other services. We don't need that.

How it works: it sets the attributes on the active span immediately, and stores
them in the OTel **context**. When any new span starts inside the block,
`LangfuseSpanProcessor.on_start()` copies them onto it. That's why the
generations and tools all carry the same user ID and session ID without any code
in the tools.

```python
178:     langfuse.update_current_span(output=response.model_dump())
179:     return response
```

- Writes `{"answer": ..., "usedTools": [...], "traceMeta": {...}}` as the agent
  span's output. Then the function returns, and `@observe` **ends** the span.

### 5.5 `app/tools.py`: tool calls become tool observations

```python
44: @observe(name="get_support_context", as_type="tool", capture_input=False)
45: def get_support_context_tool() -> dict[str, Any]:
```

- `as_type="tool"` gives the observation the tool type and icon.
- `capture_input=False`: the tool takes no arguments, so automatic capture would
  record an empty `{"args": [], "kwargs": {}}`.
- The output (Dad's device context) is captured automatically, because
  `capture_output` keeps its default of `True`.

```python
63: @observe(name="search_help_library", as_type="tool", capture_input=False)
64: def search_help_library_tool(question: str) -> dict[str, Any]:
65:     get_client().update_current_span(input={"question": question})
```

- Same pattern. Line 65 records the input as `{"question": "..."}`, the exact
  question the model asked the tool, matching the TS trace.
- The output (the matching help guides) is captured automatically.

```python
82: def execute_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
83:     if name == "get_support_context":
84:         return get_support_context_tool()
86:     if name == "search_help_library":
88:         return search_help_library_tool("" if question is None else str(question))
```

- The agent loop still calls `execute_tool(...)` exactly as before. It now
  dispatches to the traced functions, so each tool call gets its own span.

---

## 6. How separate steps become **one** trace

This is the key idea. **No code passes trace IDs around by hand.** Nesting
happens through OpenTelemetry's **context**.

### 6.1 The rule

> When a span starts, it looks at the **context**: "which span is active right
> now?" That span becomes its **parent**, and it inherits the parent's **trace
> ID**. While the new span is open, it becomes the active span itself. When it
> ends, the previous active span is restored.

The context is stored in a Python **`contextvars`** variable, which is local to
the current thread and async task. FastAPI runs our sync `/api/chat` handler in a
worker thread and copies the request's context into it, so the whole chat turn
runs with one consistent context.

### 6.2 One Bluetooth question, step by step

| # | Code running | Active span before | What happens |
| --- | --- | --- | --- |
| 1 | `run_support_conversation()` called | none of ours | `@observe` starts **span A** (agent). New trace ID `T`. A becomes active. |
| 2 | `propagate_attributes(...)` | A | user, session, name, and tags written onto A and saved in the context |
| 3 | 1st `chat.completions.create` | A | wrapper starts **span B** (generation), parent A, trace `T`, gets user and session copied on start. The model replies "call `get_support_context`". B ends. A is active again. |
| 4 | `get_support_context_tool()` | A | **span C** (tool), parent A. C ends. |
| 5 | 2nd `chat.completions.create` | A | **span D** (generation), parent A. The model replies "call `search_help_library`". |
| 6 | `search_help_library_tool(...)` | A | **span E** (tool), parent A, input `{"question": ...}`. |
| 7 | 3rd `chat.completions.create` | A | **span F** (generation), parent A. The model returns the numbered answer. |
| 8 | `run_support_conversation()` returns | A | output written, **span A ends** last |

All six spans share trace ID `T`, and B–F all point to A as their parent. That's
the whole mechanism.

### 6.3 What Langfuse builds from it

```
dad-it-support-chat-turn   (agent)       span A   input {sessionId,userId,messages}   output {answer,usedTools,traceMeta}
├── OpenAI-generation      (generation)  span B   → tool_calls: get_support_context
├── get_support_context    (tool)        span C   → Dad's iPhone 15 context
├── OpenAI-generation      (generation)  span D   → tool_calls: search_help_library
├── search_help_library    (tool)        span E   input {"question": "..."} → Bluetooth guide
└── OpenAI-generation      (generation)  span F   → final numbered answer
```

This is exactly what we read back from Langfuse during verification: 1 trace,
1 agent, 3 generations, 2 tools, all with the same user ID, session ID, name,
and tags.

### 6.4 Why the order of "end" doesn't matter

Spans end in the order C, B, D, E, F, A (children before the parent), and they
may even be uploaded in different batches. Langfuse doesn't care about arrival
order. It **merges** them on the server:

1. **Group** by trace ID → all six land in trace `T`.
2. **Link** each span to its parent by parent span ID → builds the tree.
3. **Order** siblings by start time → B, C, D, E, F.
4. **Root**: the span with no exported parent (A) becomes the trace root, and its
   input and output show as the trace's input and output.
5. **Enrich**: computes generation cost from model + tokens, and indexes user,
   session, and tags for the Users, Sessions, and filter views.

---

## 7. How spans are captured and uploaded

1. **Capture (in memory).** `@observe` and the OpenAI wrapper call the Langfuse
   tracer. Input, output, model, usage, and attributes are stored on the span as
   OTel attributes (JSON-serialized). No network call happens yet.
2. **`on_start`.** `LangfuseSpanProcessor.on_start()` copies any propagated
   attributes (user, session, tags) from the context onto the new span.
3. **`on_end`.** When a span ends, `LangfuseSpanProcessor.on_end()`:
   - drops it if it belongs to a different Langfuse project (a different public key);
   - drops it if the export filter says it isn't LLM-related (section 9);
   - otherwise puts it in the in-memory **queue**.
4. **Batch upload (background thread).** When 512 spans are queued, or every 5
   seconds, or on `flush()`, the exporter sends one **HTTPS POST** to
   `https://cloud.langfuse.com/api/public/otel/v1/traces` in OTLP format, with
   these headers:
   - `Authorization: Basic base64(public_key:secret_key)`
   - `x-langfuse-public-key`, `x-langfuse-sdk-name: python`, `x-langfuse-sdk-version`
5. **Ingest.** Langfuse stores the spans and merges them into traces (section 6.4).
   It can take a few more seconds before they show in the UI, so refresh.

Because step 4 runs on a separate thread, **the user's request never waits for
Langfuse**. If the upload fails (network down, wrong keys), the chat still
succeeds. Only that batch of traces is lost.

---

## 8. Without Langfuse keys

| What | Behavior |
| --- | --- |
| Startup | One warning: `LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY are not set. Tracing is disabled; the app still answers.` |
| `/api/health` | `"tracingConfigured": false` |
| `@observe`, OpenAI wrapper | Still run, but get a **disabled** client from `get_client()` and record nothing. The wrapped function runs normally. |
| Network | No calls to Langfuse at all |
| Shutdown | `shutdown_tracing()` returns immediately |

---

## 9. What gets uploaded, and the FastAPI span

The processor uses the default export filter `is_default_export_span`. A span is
uploaded only if it:

- was created by the Langfuse SDK (instrumentation scope `langfuse-sdk`): our
  agent, tools, and OpenAI generations; **or**
- has `gen_ai.*` attributes (the OTel GenAI semantic conventions); **or**
- comes from a known LLM instrumentation library (OpenAI, Anthropic, LangChain,
  LlamaIndex, and others).

**The FastAPI span.** Langfuse registered a global tracer provider, and FastAPI
sees it and opens its own span (`fastapi.endpoint`) around every request. That
span isn't LLM-related, so the filter drops it. Our agent span was started
**inside** it, so the agent records a parent span ID that never reaches Langfuse.
Langfuse handles this by marking the agent as the root anyway
(`isRootObservation: true`), and the tree looks the same as the TS app's. This is
expected, not a bug.

**Data sensitivity.** Prompts, tool results, and answers are uploaded in full, so
anything a user types ends up in Langfuse. For real user data, use the `mask`
option on `Langfuse(...)` to scrub sensitive fields before upload, or turn down
`sample_rate`.

---

## 10. How it was verified

`make verify-tracing` (`scripts/verify_tracing.py`) sends one real chat turn,
reads the observations back from Langfuse's `/api/public/v2/observations` API,
and checks the trace. 18 of 18 checks passed:

- `/api/health` → `tracingConfigured: true`
- exactly **one** trace per chat turn
- root observation: type `agent`, named `dad-it-support-chat-turn`, marked root
- trace name `dad-it-support-chat-turn`, tags `langfuse-workshop` and `dad-it-support`
- user ID and session ID on every observation
- root input has the `messages` array, and root output has `answer`
- 3 generations under the agent, each with a `messages` input
- one tool observation per tool call the model made, all under the agent
- with keys removed: health says `false`, two chats still answer, exactly one
  warning, no crash

It was also tested that pressing Ctrl+C immediately after a chat still delivers
the full trace (all 6 observations), thanks to `flush()` at shutdown.

---

## 11. Cheat sheet

| I want to… | Code |
| --- | --- |
| Turn on export | `Langfuse(public_key=..., secret_key=..., base_url=...)` once at startup |
| Trace an LLM call | `from langfuse.openai import OpenAI` |
| Trace any function | `@observe(name="...", as_type="span" \| "agent" \| "tool" \| ...)` |
| Set the input or output myself | `get_client().update_current_span(input=..., output=...)` |
| Attach user, session, tags | `with propagate_attributes(user_id=..., session_id=..., tags=[...]):` |
| Send everything now | `get_client().flush()` |
| Stop cleanly | `get_client().shutdown()` |

| TypeScript app | Python app |
| --- | --- |
| `new NodeSDK({ spanProcessors: [new LangfuseSpanProcessor()] }).start()` | `Langfuse(...)` |
| `observeOpenAI(new OpenAI())` | `from langfuse.openai import OpenAI` |
| `observe(fn, { name, asType })` | `@observe(name=..., as_type=...)` |
| `propagateAttributes({...}, fn)` | `with propagate_attributes(...):` |
| `forceFlush()` / `sdk.shutdown()` | `flush()` / `shutdown()` |
