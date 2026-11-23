# Python + FastAPI Port — Langfuse Workshop

## Context

The upstream `langfuse-workshop` repo teaches the Langfuse AI engineering loop
(tracing, prompt management, monitoring, datasets, experiments, evaluation) on a
single TypeScript sample app: the Dad IT Support Agent. This plan ports that app
to Python + FastAPI as a first contribution to a partner project.

Goals:

- Match the upstream app behavior and Langfuse surface, in idiomatic Python.
- Reuse shared assets (`data/`, `docs/images/`, React client) rather than fork them.
- Contribute as a sequence of small, reviewable PRs, one per workshop step.
- Keep upstream checkpoint discipline: tag each merged step as `checkpoint/py-0X-*`.

Non-goals:

- No new features beyond what the TypeScript app already does.
- No rewrite of the React client. The FastAPI server serves the existing build.
- No self-hosted Langfuse assumptions. Target Langfuse Cloud EU.

Reference behavior (from the TS app):

- `POST /api/chat` runs an OpenAI tool-calling loop, max 6 turns.
- Two local tools: `get_support_context`, `search_help_library`.
- System prompt lives in code with a Langfuse-managed prompt overriding it when present.
- One fixed support context (iPhone 15, Dad). In-memory guide library, no database.

Layout target (same repo, Python isolated under `python/`):
```
python/
  pyproject.toml          # uv-managed, [project] block + requires-python
  uv.lock                 # committed, the pinned dependency lockfile
  Makefile                # setup / app / run targets wrapping uv (see convention below)
  README.md
  .env.example
  app/
    __init__.py
    env.py                # env loading, mirrors src/server/env.ts
    support_data.py       # context + guide library, mirrors support-data.ts
    tools.py              # tool defs + executor, mirrors tools.ts
    support_agent.py      # agent loop + tracing, mirrors support-agent.ts
    server.py             # FastAPI app, mirrors index.ts
  scripts/
    publish_prompt.py
    seed_dataset.py
    run_dataset.py
```

### uv + project convention (mirror `one2n/ai_observability/base`)

- **Use `uv`, not pip.** `uv` is the source of truth for dependencies and the venv.
- **Commit `uv.lock`.** It is the pinned, reproducible lockfile and must be in version control alongside `pyproject.toml`.
- **`pyproject.toml` shape:** a `[project]` table with `name`, `version`, `description`, `requires-python` (e.g. `>=3.11`), and a `dependencies` list with lower-bound pins (e.g. `fastapi>=0.115`). No `requirements.txt` as the source of truth; generate one from `uv` only if ever needed.
- **`.venv/` is uv-managed and gitignored.** `uv sync` creates it from the lock.
- **`Makefile` wraps uv** so contributors run `make`, not raw commands. At minimum:
  - `setup:` → `uv sync`
  - `app:` → `uv run python -m app.server` (or `uv run uvicorn ...`)
  - plus curl-based smoke targets (`health`, `chat`) like the base repo's `health` / `ask`.
- **`.env` + `.env.example`** committed example, real `.env` gitignored.

Each phase below is one PR. A phase is done only when its validation criteria pass.

---

## Contribution workflow

This port is built in the fork `saurabh-hirani/langfuse-workshop`, then
contributed upstream to `langfuse/langfuse-workshop` once milestones are ready.
Upstream maintainers have agreed to accept the Python track.

Roles:

- **Contributor:** branches off the fork and raises PRs into the fork.
  Never pushes to upstream and never creates or moves tags.
- **Maintainer (of the fork):** reviews and merges those PRs, cuts the
  `checkpoint/py-0X-*` tags after merge, keeps the fork synced with upstream, and
  raises the milestone PRs from the fork to upstream.

Remotes (local clones only; the GitHub fork→upstream PR needs no remote):

- `origin` → `saurabh-hirani/langfuse-workshop` (the fork). Branch and push here.
- `upstream` → `langfuse/langfuse-workshop`. Fetch only; push is disabled.
  The contributor does not need `upstream` unless they run the sync.

Per-PR flow (contributor → fork):

- Branch off the fork's `main`: `git checkout -b py/phase-0X-<slug>`.
- Keep every change inside `python/`. Do not touch TS files, the root
  `AGENTS.md`, or any `checkpoint/*` tag.
- A PR covers exactly one phase (Phase 0 and Phase 1 are the one exception —
  they ship together, see Checkpoint tags).
- PR is mergeable only when that phase's Validation criteria all pass; state in
  the PR description what was run and its output.
- PR description: summary, what changed, how it was tested (per the Phase 8
  prep step).

Tagging (maintainer, after merge — never inside a PR):

- Cut `checkpoint/py-0X-*` from the merge commit of each phase.
- Tags live on the fork for now. They move upstream only when the milestone PR
  to upstream merges, following upstream's own tagging discipline.

Upstream sync and contribution (maintainer):

- Before a milestone upstream PR, sync the fork's `main`:
  `git fetch upstream && git checkout main && git merge upstream/main && git push origin main`.
- Raise the upstream PR from the fork: base `langfuse/langfuse-workshop:main`,
  head `saurabh-hirani/langfuse-workshop:<branch>`. First milestone is after
  Phase 0 + Phase 1.

---

## Phase 0: Scaffold and align

### Objective

Set up the Python project skeleton under `python/` and record the checkpoint
strategy so the two language tracks stay maintainable side by side.

### Steps

- [ ] Create `python/pyproject.toml` managed by `uv`: a `[project]` table with `name`, `version`, `description`, `requires-python` (`>=3.11`), and a `dependencies` list pinning `fastapi`, `uvicorn`, `openai`, `langfuse`, `pydantic`, `python-dotenv` with lower bounds. Mirror the shape of `one2n/ai_observability/base/pyproject.toml`.
- [ ] Run `uv sync` and **commit the generated `uv.lock`**. The lockfile is the pinned, reproducible source of truth and must be in version control.
- [ ] Add a `python/Makefile` wrapping uv: `setup` → `uv sync`, `app` → `uv run` the server, plus curl smoke targets (`health`, `chat`). Mirror `one2n/ai_observability/base/Makefile`.
- [ ] Create the `app/` and `scripts/` package layout with empty module stubs.
- [ ] Add `python/README.md` covering install (`make setup` / `uv sync`), run (`make app`), and the `.env` keys the Python side reads.
- [ ] Add a `python/.env.example` matching the key names in the repo root `.env.example`.
- [ ] Record the `checkpoint/py-0X-*` tag scheme and the "TS checkpoint tags contain no Python code" rule in `python/README.md` (a new `python/AGENTS.md` is also fine). Do NOT edit the root `AGENTS.md` — see the note below.
- [ ] Gitignore `python/.venv/` (uv-managed) and `python/.env`.
- [ ] Confirm the Python side reads the same root `.env` and shared `data/` files as the TS side.

> **Why not the root `AGENTS.md`:** the fork's root `AGENTS.md` opens with
> Rule 1 — any shared-file edit must be propagated onto every `checkpoint/*`
> tag via `scripts/sync-checkpoint-docs.sh`, which force-moves those TS tags.
> That directly contradicts this plan's "no change to any existing checkpoint
> tag" rule. The two cannot both hold. Resolution: keep all Python checkpoint
> notes inside `python/`, leave the root `AGENTS.md` untouched, so Rule 1 never
> fires. This also keeps the entire port isolated under `python/` as intended.

### Validation

- `uv sync` completes with no resolution errors.
- `python/uv.lock` exists and is committed.
- `python/Makefile` has at least `setup` and `app` targets; `make setup` runs `uv sync`.
- `python -c "import app"` succeeds from `python/`.
- `python/README.md` (or `python/AGENTS.md`) lists the eight `checkpoint/py-0X-*` tags and the shared-asset rule.
- No change to any existing TS file, the root `AGENTS.md`, or any existing checkpoint tag.

---

## Phase 1: Base app, no tracing

### Objective

Stand up the Dad IT Support Agent on FastAPI with the OpenAI tool-calling loop and
both local tools. Behavior matches `checkpoint/01-base-app` with no Langfuse calls.

### Steps

- [ ] Port `support_data.py`: `DEFAULT_SUPPORT_CONTEXT`, `GUIDE_LIBRARY`, `get_support_context()`, `search_guides()`. Keep the same scoring logic (term hit count, top 3).
- [ ] Port `tools.py`: the two tool JSON schemas and `execute_tool(name, args)`.
- [ ] Port `support_agent.py`: the system prompt string, the loop (max 6 turns), tool dispatch, final-answer extraction, and the fallback answer string.
- [ ] Build the FastAPI server in `server.py`: `GET /api/health`, `GET /api/support-context`, `POST /api/chat`.
- [ ] Define request/response models with Pydantic to mirror the Zod schema (session id required, messages non-empty).
- [ ] Serve the built React client and fall back to `index.html` for unknown routes.
- [ ] Read `OPENAI_API_KEY` and `OPENAI_MODEL` from env; no Langfuse keys required in this phase.
- [ ] Set the Python `OPENAI_MODEL` default to a model the contributor's key can actually call. The TS `env.ts` and the fork `.env.example` both pin `gpt-5.5-2026-04-23`; do NOT copy that blindly — confirm it resolves, or set a known-available default. A dead model string makes the `POST /api/chat` validation below fail on the first call.

### Validation

- `GET /api/health` returns `{"ok": true, "provider": "openai", "tracingConfigured": false}`.
- `GET /api/support-context` returns the iPhone 15 / Dad context matching the TS JSON.
- `POST /api/chat` with a Bluetooth question returns a numbered-step answer and lists the tools used.
- The agent calls `get_support_context` first, then `search_help_library`, matching the prompt rules.
- Invalid payload (empty messages) returns HTTP 400.
- No outbound calls to Langfuse in this phase.

---

## Phase 2: Tracing

### Objective

Add Langfuse tracing on top of the base app so each turn produces an agent trace
with generation and tool spans. Matches `checkpoint/02-tracing`.

### Steps

- [ ] Add Langfuse SDK init and OpenTelemetry export in `server.py` startup and flush on shutdown.
- [ ] Wrap the OpenAI client with the Langfuse drop-in (`from langfuse.openai import openai`).
- [ ] Decorate the agent entry with `@observe(as_type="agent")` and the two tools with `@observe(as_type="tool")`.
- [ ] Attach user id, session id, trace name, and tags per turn (the `propagate_attributes` equivalent).
- [ ] Keep the trace shape stable: message-array input on the agent/generation observations and a root `answer` field.
- [ ] Make tracing degrade cleanly when Langfuse keys are absent (log a warning, still answer).

### Validation

- With Langfuse keys set, one chat turn creates one trace named `dad-it-support-chat-turn`.
- The trace contains a generation span plus tool spans for each tool call.
- The trace carries the user id, session id, and the `langfuse-workshop` / `dad-it-support` tags.
- `GET /api/health` reports `tracingConfigured: true` when keys are present.
- With keys removed, the app still answers and logs a single warning, no crash.

---

## Phase 3: Prompt management

### Objective

Move the system prompt into Langfuse with a local fallback, and provide a publish
script for the prompt variants. Matches `checkpoint/03-prompt-management`.

### Steps

- [ ] In `support_agent.py`, fetch the managed prompt by name and fall back to the local `SYSTEM_PROMPT` when it is missing.
- [ ] Link the fetched prompt to the generation so Langfuse shows prompt-to-trace linkage.
- [ ] Port `publish_prompt.py`: publish the `default` and `gentler` variants with a configurable name and label.
- [ ] Read `LANGFUSE_PROMPT_NAME`, `LANGFUSE_PROMPT_LABEL`, and `WORKSHOP_PROMPT_VARIANT` from env with the same defaults as the TS `env.ts`.

### Validation

- `python scripts/publish_prompt.py` publishes the default variant under the configured name and label.
- Setting `WORKSHOP_PROMPT_VARIANT=gentler` publishes the gentler variant text.
- With a published prompt present, a chat turn uses it and the trace links the prompt version.
- With no published prompt, the turn falls back to the local prompt and still answers.
- An unsupported variant name exits with a clear error naming the supported variants.

---

## Phase 4: Monitoring

### Objective

Ensure the trace shape supports the monitoring evaluators the workshop configures
in the Langfuse UI (user disagreement, all-caps frustration). Mostly trace-shape
confirmation plus docs. Matches `checkpoint/04-monitoring`.

### Steps

- [ ] Confirm the message-array input and root `answer` output are present on the observations the UI evaluators map to.
- [ ] Verify a multi-turn conversation preserves the full message history on the agent observation.
- [ ] Write `python/docs` notes (or a section in `python/README.md`) pointing to the shared learner monitoring lesson and noting any Python-specific setup.
- [ ] Port the two TS trace-seed scripts to Python so this step has historical traffic to monitor:
  - `scripts/import-trace-seed-otel.ts` → `scripts/import_trace_seed_otel.py`
  - `scripts/langfuse-trace-seed-lib.ts` → a Python helper module it imports
  - Feed the shared `data/seed-traffic-followups-traces.json`; preserve the `--input` and `--no-scores` flags (TS runs them as `langfuse:seed:otel` / `langfuse:seed:otel:no-scores`).
  - This backfills traces so the monitoring evaluators have data to fire on; without it Phase 4 has no traffic beyond what the contributor generates by hand.

### Validation

- A traced multi-turn conversation exposes the last user message and full history in the fields the workshop evaluators reference.
- An all-caps user message produces a trace whose fields let the frustration evaluator fire.
- The monitoring lesson runs against Python traces without doc changes beyond the pointer notes.

---

## Phase 5: Dataset

### Objective

Seed the shared workshop dataset into Langfuse from Python. Matches
`checkpoint/05-dataset`.

### Steps

- [ ] Port `seed_dataset.py`: create the dataset if absent, then upsert items from the shared `data/seed-dataset.json`.
- [ ] Preserve each item's `input` (message array), `expectedOutput` (`idealAnswer` + `expectedKeywords`), and `metadata`.
- [ ] Read `DATASET_NAME` from env with the same default as the TS side.
- [ ] Make re-runs idempotent (creating an existing dataset is not an error).

### Validation

- `python scripts/seed_dataset.py` creates the dataset and reports the item count.
- The dataset in Langfuse contains the same items as the shared JSON, with message-array inputs and expected outputs.
- Running the script twice does not error and does not duplicate items.

---

## Phase 6: Experiments

### Objective

Run the agent against the Langfuse dataset with two callback evaluators:
deterministic keyword overlap and LLM-as-a-judge correctness. Matches
`checkpoint/06-experiments`.

### Steps

- [ ] Port `run_dataset.py`: pull the dataset by name and run each item through the same `run_support_conversation` the server uses.
- [ ] Implement `keyword_overlap`: fraction of `expectedKeywords` present in the answer, case-insensitive, returning 1 for an empty keyword list.
- [ ] Implement `correctness`: the semantic-equivalence judge prompt, one OpenAI call, JSON-only response, mapped to a 0 or 1 score with reasoning.
- [ ] Attach both evaluators as run callbacks so scores land with the run, no prior platform evaluator setup needed.
- [ ] Print a run summary and flush traces before exit.

### Validation

- `python scripts/run_dataset.py` produces one experiment run row with per-item traces.
- Every item carries a `keyword_overlap` score in `[0, 1]` and a `correctness` score in `{0, 1}`.
- The keyword overlap value matches a hand-checked count on at least one item.
- The correctness comment contains the judge's short reasoning.
- Scores appear in the Langfuse UI under the run name.

---

## Phase 7: Evaluation

### Objective

Change one thing (the prompt variant), rerun the same dataset, and compare the two
runs on the same scores. Matches `checkpoint/07-evaluation`.

### Steps

- [ ] Publish the `gentler` prompt variant using the Phase 3 script.
- [ ] Rerun `run_dataset.py` against the same dataset with the new prompt in effect.
- [ ] Confirm the two runs are comparable side by side on `keyword_overlap` and `correctness`.
- [ ] Document the compare step in the Python notes with a pointer to the shared learner evaluation lesson.

### Validation

- Two runs exist for the same dataset, one per prompt variant.
- Both runs report the same two score names, enabling a side-by-side compare in the UI.
- The Python notes describe how to read the diff between runs.

---

## Phase 8: Wrap-up

### Objective

Finish the Python track: complete the README, verify the full path end to end, and
prepare the contribution for review. Matches `checkpoint/08-wrap-up`.

### Steps

- [ ] Complete `python/README.md`: setup, run, each script, and the mapping from Python modules to the shared workshop lessons.
- [ ] Verify the full loop on a clean checkout: install, run app, publish prompt, seed dataset, run experiment, compare.
- [ ] Confirm no changes leaked into existing TS files or existing checkpoint tags.
- [ ] Prepare PR descriptions for each phase (summary, what changed, how it was tested).

### Validation

- A clean-checkout run of the full loop succeeds with only the documented env keys.
- `python/README.md` maps every Python module and script to its workshop step.
- The diff touches only `python/` plus the single agreed `AGENTS.md` edit.
- Each phase has a merge commit tagged `checkpoint/py-0X-*`.

---

## Checkpoint tags

Cut each tag from the merge commit of its phase:

- `checkpoint/py-00-setup` and `checkpoint/py-01-base-app` — Phase 0 and Phase 1
  - Shipped as a **single PR** with both tags cut off the same merge commit. The TS repo keeps `00-setup` ≡ `01-base-app`, and the base app needs no Langfuse, so the two phases land together.
- `checkpoint/py-02-tracing` — Phase 2
- `checkpoint/py-03-prompt-management` — Phase 3
- `checkpoint/py-04-monitoring` — Phase 4
- `checkpoint/py-05-dataset` — Phase 5
- `checkpoint/py-06-experiments` — Phase 6
- `checkpoint/py-07-evaluation` — Phase 7
- `checkpoint/py-08-wrap-up` — Phase 8

## Langfuse Python SDK drift — verify before Phase 2 and Phase 6

The app logic ports almost verbatim. The friction is that the Langfuse Python
SDK surface differs from the TS `@langfuse/*` packages. Confirm the exact names
against the installed `langfuse` version before writing Phase 2 and Phase 6:

- `observeOpenAI(new OpenAI())` (TS) → `from langfuse.openai import openai` (Python drop-in).
- `observe(...)` wrapper (TS) → `@observe(as_type="agent" | "tool")` decorator (Python).
- `propagateAttributes({ userId, sessionId, traceName, tags })` (TS) → the Python
  attribute-propagation call, whose name varies by SDK version (e.g.
  `langfuse.update_current_trace(...)` / context helpers). This is the one the
  plan phrases as an "equivalent" — verify it.
- `dataset.runExperiment({ task, evaluators })` (TS) → the Python experiment
  runner has a different shape. Phase 6 is the highest-friction phase; budget
  time to map the runner and the two callback evaluators.

## Decisions settled (previously open questions)

- **AGENTS.md:** do not edit the root `AGENTS.md`. Put the Python checkpoint
  scheme and shared-asset rule in `python/`. See the note in Phase 0 for why
  (root `AGENTS.md` Rule 1 would force-move the TS checkpoint tags).
- **Package manager:** `uv`, and `uv` only. Commit `uv.lock`; `pyproject.toml`
  uses a `[project]` table with `requires-python`; a `Makefile` wraps uv.
  Mirror the layout of `one2n/ai_observability/base` (`pyproject.toml` +
  `uv.lock` + `Makefile` + `.env.example`). No `requirements.txt` as the source
  of truth; generate one from uv only if ever needed.
- **Docs:** parallel `python/docs` with pointer notes into the shared learner
  lessons. Do not fork the shared doc tree.
- **Model pin:** set a Python-side `OPENAI_MODEL` default to a currently
  callable model; do not blindly reuse the TS `gpt-5.5-2026-04-23` pin. See
  Phase 1.
- **Phase 0 + Phase 1 delivery:** one PR, two tags (`py-00-setup`,
  `py-01-base-app`) off the same merge commit.
- **Phase 4 traffic seeding:** port the two TS trace-seed scripts to Python.
  See Phase 4.

## Still needs the maintainer's call

- None. All prior open questions are decided above.