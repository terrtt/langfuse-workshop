# Dad IT Support Agent — Python + FastAPI track

A Python + FastAPI port of the workshop's Dad IT Support Agent. It matches the
TypeScript app's behavior and API, and reuses the shared repo assets (`data/`,
`docs/`, and the React client) instead of forking them.

Learners follow the Python lessons in [`learners/`](learners/), one per
workshop step. They reuse the shared screenshots and point back to the TS lessons
in [`../docs/learner/`](../docs/learner/) for the concepts.

| Step | Python lesson | Shared (TS) lesson |
| --- | --- | --- |
| 00 Setup | [`learners/00-setup.md`](learners/00-setup.md) | [`docs/learner/00-setup.md`](../docs/learner/00-setup.md) |
| 01 Base app | [`learners/01-base-app.md`](learners/01-base-app.md) | [`docs/learner/01-base-app.md`](../docs/learner/01-base-app.md) |
| 02 Tracing | [`learners/02-tracing.md`](learners/02-tracing.md) | [`docs/learner/02-tracing.md`](../docs/learner/02-tracing.md) |
| 03 Prompt management | [`learners/03-prompt-management.md`](learners/03-prompt-management.md) | [`docs/learner/03-prompt-management.md`](../docs/learner/03-prompt-management.md) |

Lessons for steps 04 to 08 are added with each phase's code.

## Install

Requires [uv](https://docs.astral.sh/uv/) and Python 3.11+.

```bash
cd python
make setup        # runs `uv sync`, creating .venv/ from uv.lock
```

`uv` is the only package manager for this track. `pyproject.toml` lists the
dependencies, and `uv.lock` (committed) pins them. Do not add a
`requirements.txt`.

## Configure

The Python app reads the same **repo-root `.env`** as the TypeScript app, so one
config file serves both tracks. If you need a Python-only override, copy
`.env.example` to `python/.env`; values there win over the root file.

| Key | Used from | Default on the Python side |
| --- | --- | --- |
| `OPENAI_API_KEY` | py-01 | none (required) |
| `OPENAI_MODEL` | py-01 | `gpt-4.1-mini` |
| `OPENAI_BASE_URL` | py-01 (optional) | OpenAI API; set it for an OpenAI-compatible gateway |
| `PORT` | py-01 | `8787` |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` | py-02 | none (tracing is off without them) |
| `LANGFUSE_BASE_URL` | py-02 | `https://cloud.langfuse.com` |
| `LANGFUSE_PROMPT_NAME` | py-03 | `dad-it-support-agent` |
| `LANGFUSE_PROMPT_LABEL` | py-03 | `production` |
| `WORKSHOP_PROMPT_VARIANT` | py-03 | `default` |
| `DATASET_NAME` | py-05 | `dad-it-support-workshop` |

The TypeScript app defaults `OPENAI_MODEL` to `gpt-5.5-2026-04-23`. The Python
side defaults to `gpt-4.1-mini` because it is broadly available; set
`OPENAI_MODEL` to any chat model your key can call.

The base app (`checkpoint/py-01-base-app`) needs only the OpenAI keys. From
`checkpoint/py-02-tracing` onward, the Langfuse keys turn on tracing. Without them
the app logs one warning at startup and keeps answering, untraced.

## Run

```bash
make app          # Python API on http://127.0.0.1:8787 + React UI on http://127.0.0.1:3333
```

`make app` starts both processes in one terminal: the FastAPI server and the
shared React dev UI (`npm run dev:client` from the repo root). Open
http://127.0.0.1:3333 to chat. The UI sends `/api` requests to port 8787 (set in
`../vite.config.ts`), so keep the API on the default port when you use the UI.
Ctrl+C stops both. If the API fails to start, for example because the TS server
already holds port 8787, the UI stops too. The first run installs the root npm
packages if `node_modules/` is missing.

Other run targets:

| Target | Starts |
| --- | --- |
| `make api` | Python API only (any `PORT=...`) |
| `make ui` | React dev UI only |
| `make client` | Builds the UI into the repo-root `dist/`, which the API then serves at http://127.0.0.1:8787 without the dev UI |

Smoke checks, with the server running in another terminal:

```bash
make health        # {"ok": true, "provider": "openai", "tracingConfigured": false}
make context       # Dad's iPhone 15 support context
make chat          # Bluetooth question -> numbered steps + usedTools
make chat-invalid  # empty messages -> 400
```

## Tracing (py-02)

Each chat turn becomes one Langfuse trace named `dad-it-support-chat-turn`:

```
dad-it-support-chat-turn   (agent)       input: {sessionId, userId, messages}   output: {answer, usedTools, traceMeta}
├── OpenAI-generation      (generation)  -> calls get_support_context
├── get_support_context    (tool)
├── OpenAI-generation      (generation)  -> calls search_help_library
├── search_help_library    (tool)        input: {question}
└── OpenAI-generation      (generation)  -> final numbered answer
```

The trace carries the user ID, the session ID, and the tags `langfuse-workshop`
and `dad-it-support`. The step-by-step Python lesson, with the shared screenshots,
is [`learners/02-tracing.md`](learners/02-tracing.md). For a line-by-line
explanation of how tracing works (the export pipeline, every parameter, and how
spans nest into one trace), see [`TRACING-EXPLAINED.md`](TRACING-EXPLAINED.md).

Check every Phase 2 validation criterion against Langfuse:

```bash
make api              # terminal 1
make verify-tracing   # terminal 2: 18 checks, including a keys-removed run on port 8799
```

## Prompt management (py-03)

The app fetches its system prompt from Langfuse (`LANGFUSE_PROMPT_NAME` with the
label `LANGFUSE_PROMPT_LABEL`) on each turn, through the SDK's 60-second cache, and
links every generation to that prompt version. If the prompt is missing or Langfuse
is unreachable, it falls back to the local `SYSTEM_PROMPT`. Publish the local prompt
to Langfuse with:

```bash
make prompt-publish                                  # SYSTEM_PROMPT, labelled production
WORKSHOP_PROMPT_VARIANT=gentler make prompt-publish  # the gentler tone variant used in 07
```

Each run creates a new prompt version. The step-by-step lesson is
[`learners/03-prompt-management.md`](learners/03-prompt-management.md).

## Parity check against the TypeScript base app

This check belongs to `checkpoint/py-01-base-app`. From py-02 onward, the Python
`/api/health` reports `tracingConfigured: true` when Langfuse keys are set, while
the TS base app always reports `false`. That one check is then expected to differ.

`scripts/parity_check.py` sends the same requests to the TypeScript base app
(`checkpoint/01-base-app`) and to the Python app, then compares the responses.
It runs 24 checks:

| Area | Checks | Expectation |
| --- | --- | --- |
| `GET /api/health`, `GET /api/support-context` | 2 | Identical JSON from both apps |
| `POST /api/chat` with invalid payloads (empty messages, missing sessionId, empty sessionId, bad role, empty content) | 5 | Both apps return HTTP 400 |
| Unknown client route (`/some/client/route`) | 1 | Both serve the React `index.html` |
| `POST /api/chat` with 4 starter questions (Bluetooth, WhatsApp photo, Wi-Fi, bus stop) | 4 per question, 16 total | Same response keys, same `traceMeta`, same `usedTools` in the same order (`get_support_context` then `search_help_library`), and a numbered-step answer from both |

Chat answers come from an LLM, so wording varies between runs, even on the same
app. The script compares behavior and response shape, not exact text, and
prints the start of each answer side by side for a manual read.

Do not compare against a TS server started from `main` or a later checkpoint.
Those include tracing and prompt management. Run the base app from its tag in a
separate worktree:

```bash
# Terminal 1: TS base app on port 8790
cd <repo-root>
git worktree add --detach ../ts-base checkpoint/01-base-app
ln -s "$PWD/node_modules" ../ts-base/node_modules
ln -s "$PWD/.env"         ../ts-base/.env
ln -s "$PWD/dist"         ../ts-base/dist
cd ../ts-base && PORT=8790 npx tsx src/server/index.ts

# Terminal 2: Python app on port 8788
cd <repo-root>/python && make api PORT=8788

# Terminal 3: compare
cd <repo-root>/python
uv run python scripts/parity_check.py --ts http://127.0.0.1:8790 --py http://127.0.0.1:8788

# Clean up: stop both servers, then
cd <repo-root> && git worktree remove --force ../ts-base
```

The script exits non-zero if any check fails.

Last recorded run (2026-10-18, `OPENAI_MODEL=openai/gpt-4.1-mini` through
OpenRouter): **24 of 24 checks passed.**

```text
PASS  GET /api/health identical
PASS  GET /api/support-context identical
PASS  POST /api/chat invalid: empty messages  (ts=400 py=400)
PASS  POST /api/chat invalid: missing sessionId  (ts=400 py=400)
PASS  POST /api/chat invalid: empty sessionId  (ts=400 py=400)
PASS  POST /api/chat invalid: bad role  (ts=400 py=400)
PASS  POST /api/chat invalid: empty content  (ts=400 py=400)
PASS  unknown route -> index.html
--- How do I turn Bluetooth on on my iPhone?
PASS  response keys / traceMeta / usedTools / numbered steps
--- How do I take a photo and send it on WhatsApp?
PASS  response keys / traceMeta / usedTools / numbered steps
--- How do I reconnect my iPhone to Wi-Fi?
PASS  response keys / traceMeta / usedTools / numbered steps
--- How do I find directions to a bus stop in Maps?
PASS  response keys / traceMeta / usedTools / numbered steps
ALL CHECKS PASSED
```

## Layout

| Python module | Mirrors (TypeScript) | Purpose |
| --- | --- | --- |
| `app/env.py` | `src/server/env.ts`, `load-env.ts` | Env loading and defaults |
| `app/support_data.py` | `src/server/support-data.ts` | Fixed Dad context and guide library |
| `app/tools.py` | `src/server/tools.ts` | Tool JSON schemas, `execute_tool`, and the `tool` observations (py-02) |
| `app/support_agent.py` | `src/server/support-agent.ts` | System prompt, the tool-calling loop (max 6 turns), the root `agent` observation (py-02), and the Langfuse prompt fetch with local fallback (py-03) |
| `app/tracing.py` | Tracing setup in `src/server/index.ts` | Langfuse client start and flush (py-02) |
| `app/server.py` | `src/server/index.ts` | FastAPI routes and React client serving |
| `scripts/publish_prompt.py` | `scripts/publish-prompt.ts` | Publishes `SYSTEM_PROMPT` (or the `gentler` variant) to Langfuse with the production label (py-03) |
| `scripts/seed_dataset.py` | `scripts/seed-dataset.ts` | Stub until py-05 |
| `scripts/run_dataset.py` | `scripts/run-dataset.ts` | Stub until py-06 |
| `scripts/parity_check.py` | (Python only) | Compares the Python app with the TS base app over HTTP (py-01) |
| `scripts/verify_tracing.py` | (Python only) | Checks the py-02 tracing criteria against Langfuse |
| `learners/00-setup.md` … `learners/03-prompt-management.md` | `docs/learner/0X-*.md` | Python learner lessons (see below) |

## Checkpoints

The Python track has its own checkpoint tags. Each tag is cut from the merge
commit of its phase:

| Tag | Workshop step |
| --- | --- |
| `checkpoint/py-00-setup` | Setup (same commit as py-01) |
| `checkpoint/py-01-base-app` | Base app, no tracing |
| `checkpoint/py-02-tracing` | Langfuse tracing |
| `checkpoint/py-03-prompt-management` | Managed prompt with local fallback |
| `checkpoint/py-04-monitoring` | Monitoring evaluators |
| `checkpoint/py-05-dataset` | Seed the workshop dataset |
| `checkpoint/py-06-experiments` | Dataset experiments with callback evaluators |
| `checkpoint/py-07-evaluation` | Compare prompt variants |
| `checkpoint/py-08-wrap-up` | Recap and next steps |

`py-00-setup` and `py-01-base-app` point at the same commit, as `00-setup` and
`01-base-app` do on the TypeScript track.

Rules for maintainers:

- **TS checkpoint tags contain no Python code.** Never move or edit an existing
  `checkpoint/0X-*` tag to add Python work. Python work only lands on
  `checkpoint/py-0X-*` tags.
- **Shared assets stay shared.** The Python side reads `data/`, `docs/`, and the
  React client build from the repo root. Do not copy or fork them into `python/`.
  When the workshop data changes, both tracks pick it up.
- **Keep Python changes inside `python/`.** Do not edit TypeScript files or the
  root `AGENTS.md` from this track. Root `AGENTS.md` Rule 1 would force-move every
  TS checkpoint tag, so Python checkpoint notes live here instead.
- Contributors open PRs into the fork. Only the fork maintainer cuts
  `checkpoint/py-0X-*` tags, after merge.
