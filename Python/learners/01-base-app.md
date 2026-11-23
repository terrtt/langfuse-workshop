---
title: "Workshop (Python): Dad IT Support Agent Base App"
description: "Tour the Python support agent before instrumentation: chat UI, FastAPI server, OpenAI tool loop, local tools, and support data."
---

# 01 Base App (Python)

> This is the Python version of [`docs/learner/01-base-app.md`](../../docs/learner/01-base-app.md).
> You already set up the app in `00-setup`, and the base app is in that same
> checkout. There is nothing to build in this chapter. Get oriented before tracing
> starts in `02-tracing`.

```bash
git checkout checkpoint/py-01-base-app
```

## What the running app does

- Dad himself is the user. Specs, the agent, talks directly to him about his iPhone.
- One OpenAI tool-calling loop, up to 6 rounds, with two local tools:
  `get_support_context` and `search_help_library`.
- The system prompt is a string in `app/support_agent.py`. No Langfuse yet.

![How Specs handles a ticket: one agent, two tools, one model, each hop an observation in the trace.](../../docs/images/specs_illustration.png)

## How a request travels

```
Browser (React UI, :3333)
   │  POST /api/chat  {sessionId, userId, messages}
   ▼
Vite dev server ── proxies /api ──► FastAPI (app/server.py, :8787)
                                       │  Pydantic validates the body (400 on bad input)
                                       ▼
                       run_support_conversation()  (app/support_agent.py)
                         loop: OpenAI chat.completions.create(tools=...)
                               └─ tool call? → execute_tool()  (app/tools.py)
                                                 └─ support_data.py
                         returns {answer, usedTools, traceMeta}
```

The React UI is shared with the TypeScript track (`src/client/` in the repo root).
Only the server is in Python.

## Where to look in the code

All paths are inside `python/`:

| File | What it holds | TypeScript original |
| --- | --- | --- |
| `app/server.py` | FastAPI routes: `GET /api/health`, `GET /api/support-context`, `POST /api/chat`, and the React build fallback | `src/server/index.ts` |
| `app/support_agent.py` | The system prompt, the tool-calling loop you'll instrument in `02-tracing`, and the Pydantic request/response models | `src/server/support-agent.ts`, `src/shared/types.ts` |
| `app/tools.py` | Tool JSON schemas (`TOOL_DEFINITIONS`) and `execute_tool(...)` | `src/server/tools.ts` |
| `app/support_data.py` | Dad's fixed context and the guide library with its keyword search | `src/server/support-data.ts` |
| `app/env.py` | Loads the repo-root `.env` and sets defaults | `src/server/env.ts`, `load-env.ts` |

Things worth noticing before you add tracing:

- `run_support_conversation()` makes **several** OpenAI calls per question: one
  to pick a tool, one after each tool result, and one for the final answer. Right
  now you only see the final answer.
- The prompt rules tell the model to call `get_support_context` first and
  `search_help_library` before answering. `usedTools` in the response shows
  whether it did.
- Invalid payloads (empty `messages`, missing `sessionId`) return HTTP 400, the
  same as the TS app.

## Bonus

You can make the replies match a real phone by changing the specs in
`app/support_data.py`. Edit `DEFAULT_SUPPORT_CONTEXT` with your dad's phone and
apps, then restart `make app`.

## End state

You are ready to start [`02-tracing`](02-tracing.md).
