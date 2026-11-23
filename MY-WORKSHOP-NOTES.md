# My Langfuse Workshop Notes — Dad IT Support Agent

Personal notes for the Langfuse workshop (modules 01–07). For each module: **what it is → how we did it → what it gives us → issues I hit**. Modules 06 and 07 get a deep dive at the end, plus the overall mental model.

> This file is untracked by git, so it stays put when I `git checkout checkpoint/*`.

---

## How data travels — from a wrapped function to a Langfuse trace

Wrapping a function doesn't send anything to Langfuse by itself. It records a **span** (a timed record of one step: input, output, start and end time) in memory. Separately, the code in `index.ts` collects those spans and uploads them in the background. A trace gets to Langfuse in five stages.

### The pipeline

```
 ① wrapped function runs      ② span is created & nested     ③ span ends
 observe(...) / observeOpenAI  (OpenTelemetry tracer)         (function returns)
            │                            │                          │
            ▼                            ▼                          ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │                     your Node process (memory)                         │
 │                                                                        │
 │   ④ LangfuseSpanProcessor  ── queues finished spans in a batch ──┐     │
 └──────────────────────────────────────────────────────────────────┼─────┘
                                                                    │ background HTTP
                                                                    ▼  (OTLP format)
                          ⑤ Langfuse Cloud  →  builds the trace tree  →  Tracing UI
```

#### ① Start the tracing system (`index.ts`, once at startup)
```ts
const langfuseSpanProcessor = new LangfuseSpanProcessor();
const sdk = new NodeSDK({ spanProcessors: [langfuseSpanProcessor] });
sdk.start();
```
This sets up two things:
- **OpenTelemetry**, the standard tracing system, which all the wrappers report to.
- **`LangfuseSpanProcessor`**, which collects finished spans and uploads them. It reads `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` and `LANGFUSE_BASE_URL` from `.env`.

If this code is missing, the wrappers still run, but nothing ever gets uploaded.

#### ② Each wrapped call opens a span, nested under its caller
When Dad asks "How do I turn Bluetooth on?":

```
runSupportConversation(request)          ← observe(..., asType:"agent") opens span A
│                                          records input = request
├─ openai.chat.completions.create()      ← observeOpenAI opens span B (generation)
│                                          records model, messages, tokens, latency
├─ getSupportContextTool()               ← observe(..., asType:"tool") opens span C
├─ openai.chat.completions.create()      ← span D
├─ searchHelpLibraryTool({question})     ← span E
└─ openai.chat.completions.create()      ← span F
                                           span A ends, records output = answer
```

**How does span C know it belongs under span A?** Node's async context tracking remembers which span is currently active, even across `await`. When `getSupportContextTool()` runs, OpenTelemetry sees that span A is open, so it gives span C:
- the same **trace ID** as span A
- span A as its **parent**

That's why I never pass IDs around by hand: all six spans share one trace ID, and that's what makes them one trace.

`propagateAttributes({ userId, sessionId, tags })` uses the same mechanism, so every span created inside that block gets those values attached.

#### ③ The span closes when the function returns
When a wrapped function finishes, its span records the end time and the output, and is marked finished. Only finished spans are passed to the processor.

The child spans (B–F) finish first, and span A finishes last, when the whole turn is done.

#### ④ `LangfuseSpanProcessor` uploads them in batches
The processor doesn't make one HTTP call per span. It queues finished spans and sends a batch when:
- enough spans have built up, or
- a short timer fires, or
- `forceFlush()` is called.

The upload is an HTTPS POST in the standard OpenTelemetry format (OTLP) to Langfuse's OpenTelemetry endpoint, authenticated with my public and secret key. It runs in the background, so **Dad's answer is never delayed by tracing**. If Langfuse is down, the chat still works; only those traces are lost.

This is also why `shutdown()` has:
```ts
await langfuseSpanProcessor.forceFlush();   // send whatever is still queued
await sdk.shutdown();
```
Without it, pressing Ctrl+C can discard the last batch, and the most recent trace never appears.

#### ⑤ Langfuse rebuilds the tree
Langfuse receives the spans, groups them by trace ID, and uses the parent links to rebuild the tree. It uses the type given to each wrapper (`agent`, `generation`, `tool`) to show the right icon and fields, such as token usage and cost for generations. That's why traces appear a few seconds after chatting and the UI needs a refresh.

### The same thing, shorter

| Piece | Job |
| --- | --- |
| `observe(fn, {asType})` | Opens a span when `fn` starts and closes it when `fn` returns, recording input and output |
| `observeOpenAI(client)` | The same, for every OpenAI call, plus model, tokens and cost |
| Async context tracking | Remembers the active span, so child spans nest automatically |
| `LangfuseSpanProcessor` | Queues finished spans and uploads them to Langfuse in the background |
| `forceFlush()` / `shutdown()` | Sends whatever is still queued before the process exits |
| Langfuse Cloud | Groups spans by trace ID and shows the tree in the Tracing UI |

`npm run dataset:run` in step 06 works the same way. The script starts its own `NodeSDK` and `LangfuseSpanProcessor`, calls the same wrapped `runSupportConversation()`, and flushes at the end. That's why experiment traces look exactly like production traces.

---

## 0. The big picture — the AI engineering loop

```
        ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
        │ 02 Tracing   │ ──► │ 04 Monitoring│ ──► │ 05 Dataset   │
        │ see every    │     │ flag the     │     │ write down   │
        │ step         │     │ bad traces   │     │ what "good"  │
        └──────▲───────┘     └──────────────┘     │ looks like   │
               │                                  └──────┬───────┘
               │                                         ▼
        ┌──────┴───────┐     ┌──────────────┐     ┌──────────────┐
        │ ship / deploy│ ◄── │ 07 Evaluate  │ ◄── │ 06 Experiment│
        │ (03 prompt   │     │ change 1     │     │ run + score  │
        │  mgmt makes  │     │ thing, rerun,│     │ whole dataset│
        │  this cheap) │     │ compare      │     │ (baseline)   │
        └──────────────┘     └──────────────┘     └──────────────┘
```

**Observe → detect → collect → measure → change → measure again → ship.** Each module adds one piece of that loop to the same app.

### The app ("Specs", the Dad IT Support Agent)
- React chat UI (`src/client/App.tsx`) → Vite dev server on `http://127.0.0.1:3333` → proxies `/api` to the Express server on `127.0.0.1:8787` (`src/server/index.ts`).
- `runSupportConversation()` (`src/server/support-agent.ts`) runs an OpenAI **tool-calling loop** (up to 6 rounds) with two local tools (`src/server/tools.ts`):
  - `get_support_context` — Dad's fixed phone setup
  - `search_help_library` — searches the iPhone help guides in `support-data.ts`
- Config comes from `.env` (loaded by `src/server/load-env.ts` with `override: true`).

---

## 1. How data gets from my app to Langfuse

There are **four channels** of data flowing to Langfuse Cloud:

```
 My Node process                                           Langfuse Cloud (EU)
 ─────────────────────────────────────────                 ─────────────────────
 observe(fn, {asType:"agent"|"tool"})  ─┐
 observeOpenAI(new OpenAI())           ─┼─► OpenTelemetry spans
 propagateAttributes({userId,...})     ─┘   │
                                            ▼
                         LangfuseSpanProcessor (batches) ──OTLP/HTTP──► Traces / Observations
                                                                         (Tracing tab)

 LangfuseClient.prompt.get(name)  ◄──────────── REST (cached) ────────── Prompts
 LangfuseClient.api.datasets/... ───────────── REST ─────────────────► Datasets + items
 dataset.runExperiment(...)      ───── spans + run items + scores ───► Experiments / Scores

                                     Langfuse-side evaluators (04) read ingested
                                     observations and write Scores back — runs in Langfuse,
                                     using the LLM Connection configured in Langfuse.
```

### 1a. Traces (OpenTelemetry)
1. `src/server/index.ts` starts an OpenTelemetry `NodeSDK` with a `LangfuseSpanProcessor`. The processor reads `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL` from env.
2. Every wrapped function call creates a **span** (an "observation" in Langfuse):
   - `observe(runSupportConversationInner, { name: "dad-it-support-chat-turn", asType: "agent" })` → root observation. Function **argument = input**, **return value = output**.
   - `observeOpenAI(new OpenAI(...))` → one **generation** per `chat.completions.create` call, with model, messages, response, token usage, latency (and cost if Langfuse knows the model's price).
   - `observe(..., { asType: "tool" })` around each tool → tool observations with tool input/output.
3. Because these all run inside the same async context, OpenTelemetry nests them automatically → **one chat turn = one trace tree**.
4. The span processor **batches** spans and sends them over OTLP/HTTP in the background. That's why the shutdown handler calls `forceFlush()` — otherwise the last trace can be lost/late when I stop the server.

Trace shape for one turn:
```
dad-it-support-chat-turn   (agent)    input: {messages:[...]}   output: {answer, ...}
├── OpenAI-generation      (generation)  → decides to call get_support_context
├── get_support_context    (tool)
├── OpenAI-generation      (generation)  → decides to call search_help_library
├── search_help_library    (tool)
└── OpenAI-generation      (generation)  → final numbered answer
```

### 1b. Prompts (REST, pull)
`langfuse.prompt.get("dad-it-support-agent")` fetches the version labelled `production`. Passing `{ langfusePrompt }` into `observeOpenAI` links each generation to that prompt version.

### 1c. Datasets (REST, push)
`npm run dataset:seed` → `langfuse.api.datasets.create(...)` + `datasetItems.create(...)` for each of the 14 items in `data/seed-dataset.json`.

### 1d. Experiments + scores
`npm run dataset:run` → `dataset.runExperiment(...)` creates the per-item traces (same OTel path as above), links each trace to a dataset item under one **run name**, and writes the evaluator results as **scores** on those traces.

---

## 2. Module-by-module notes

### 01 — Base app
| | |
|---|---|
| **What** | Tour of the untraced agent before adding Langfuse. |
| **How** | `git checkout checkpoint/01-base-app`, `npm install`, `npm run dev`, ask a question at `http://127.0.0.1:3333`. Read `support-agent.ts` (tool loop), `tools.ts` (2 tools), `support-data.ts` (Dad's context + guides). |
| **What it gives** | Baseline understanding: one agent, one model, two tools. Black box — I can see the answer but not *how* it got there. |

**Issues I faced**
1. **`429 You have no credits remaining`** — my OpenAI key had no credits. Fix: the app uses the official `openai` SDK, which honors `OPENAI_BASE_URL`, so any OpenAI-compatible provider works with **zero code changes**. I first set up Google Gemini (free tier):
   ```env
   OPENAI_API_KEY=<gemini key>
   OPENAI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
   OPENAI_MODEL=gemini-3.5-flash
   ```
2. **`404 ... models/gemini-2.5-flash is no longer available to new users`** — that model is retired for new accounts. Fix: use a current model (listed with `GET .../openai/models`).
3. **Still got the OpenAI 429 after editing `.env`** — the server was started *before* I edited `.env`. `tsx watch` restarts on code changes but **does not watch `.env`**. Fix: **Ctrl+C and `npm run dev` again after every `.env` change.**
4. **`503 status code (no body)`** — Google free tier overloaded (`gemini-3.8-flash`, `gemini-flash-latest`). Fix: switched to `gemini-3.5-flash`, which responded.
5. **The "OpenAI key" I got later was actually an OpenRouter key** (`sk-or-v1-...`). OpenAI keys start with `sk-proj-` / `sk-`. Fix — point at OpenRouter:
   ```env
   OPENAI_API_KEY=sk-or-v1-...
   OPENAI_BASE_URL=https://openrouter.ai/api/v1
   OPENAI_MODEL=openai/gpt-4.1-mini
   ```
   Verified tool calling + JSON mode both work. (With a real OpenAI key: delete `OPENAI_BASE_URL`, set `OPENAI_MODEL=gpt-4.1-mini`.)

> Rule of thumb: any provider works as long as it supports **tool calling** (the agent) and **`response_format: json_object`** (the step-06 judge).

---

### 02 — Tracing
| | |
|---|---|
| **What** | Make every step of a chat turn visible in Langfuse as one nested trace. |
| **How** | 3 steps on `checkpoint/02-tracing`:<br>1. `index.ts`: start `NodeSDK` + `LangfuseSpanProcessor`; flush + shutdown in `shutdown()`.<br>2. `support-agent.ts`: `observeOpenAI(new OpenAI(...))`; rename the function to `runSupportConversationInner` and export `observe(runSupportConversationInner, { name: "dad-it-support-chat-turn", asType: "agent" })`.<br>3. `tools.ts`: wrap both tools with `observe(..., { asType: "tool" })` and call the wrapped versions from `executeTool`.<br>Bonus: `propagateAttributes({ userId, sessionId, tags }, ...)` to fill the Users/Sessions views. |
| **What it gives** | The black box becomes a debugging surface: every model call (prompt, response, tokens, latency, cost), every tool call (input/output), in order. When an answer is wrong I can point at the exact step. |

**Issues I faced**
- None specific to tracing beyond the provider issues in 01.

**Watch out for**
- `Multiple exports with the same name "executeTool"` → the old `executeTool` is still in `tools.ts`; delete it.
- Last trace missing after stopping the server → the `forceFlush()` in `shutdown()` fixes it.
- With Gemini/OpenRouter, the cost column may show **$0 or be missing**: Langfuse prices by model name and may not know `gemini-*` or `openai/gpt-4.1-mini`. Tokens and latency are still recorded.

---

### 03 — Prompt management
| | |
|---|---|
| **What** | Move the system prompt out of code into Langfuse (versioned, labelled, editable in the UI) and fetch it at request time. |
| **How** | 1. Langfuse UI → Prompts → New prompt: name `dad-it-support-agent`, type `text`, body = `SYSTEM_PROMPT`, label `production` (or `npm run prompt:publish`).<br>2. In `support-agent.ts`: `new LangfuseClient()`, `getPrompt()` returns `null` on failure, `systemPrompt = langfusePrompt?.prompt ?? SYSTEM_PROMPT`, use `systemPrompt` as the system message, pass `{ langfusePrompt }` to `observeOpenAI`. |
| **What it gives** | Prompt changes without a code deploy; non-engineers can iterate; every generation shows a **Prompt badge** linking to the exact version that produced it. A **local fallback** keeps the app working if Langfuse is unreachable. |

**Issues I faced**
- None specific to this step.

**Watch out for**
- Forgetting to change `{ role: "system", content: SYSTEM_PROMPT }` → badge appears but edits in Langfuse have no effect.

---

### 04 — Monitoring
| | |
|---|---|
| **What** | Automatically flag interesting production traces instead of reading them all. |
| **How** | No code. In the Langfuse UI:<br>0. **Project Settings → LLM Connections** — the model Langfuse uses for LLM-as-a-judge.<br>1. **Detect User Disagreement** (LLM judge) on the root `dad-it-support-chat-turn` agent observation; map `{{conversation_history}}` → Input → all messages, `{{last_user_message}}` → Input → last message; test, create, execute.<br>2. **Detect User Frustration (ALL CAPS)** (TypeScript code evaluator, no LLM) on the same root observation.<br>Verify: send "No, that menu isn't there" and "THIS STILL ISNT WORKING", then filter Tracing by score. Seed realistic traffic with `npm run langfuse:seed:otel:no-scores` (run **once**; it is not idempotent). |
| **What it gives** | **Signal detection**: scores on live traces that tell me *which traces to read first*. Disagreement = high signal (the agent probably got something wrong). ALL CAPS = cheap, rough signal. Flagged traces become dataset candidates for 05. |

**Issues I faced**
1. **LLM Connection test failed with `models/gemini-2.5-flash is no longer available`** — the `.env` model does **not** apply here; Langfuse has its own connection and its built-in Google model list still offered the retired model. Fix: in the connection's advanced settings, turn **off default models** and add a **custom model** (`gemini-3.5-flash`).
2. **`models/gemini-3.5-flash. is not found for API version v1beta`** — there was a **trailing dot** in the custom model name (copy/paste). Fix: type exactly `gemini-3.5-flash`.
3. Alternative with my OpenRouter key: adapter `openai`, API base URL `https://openrouter.ai/api/v1`, custom model `openai/gpt-4.1-mini`.

> Key learning: **two separate model configs exist** — `.env` (my app + my experiment scripts) and **Langfuse LLM Connections** (Langfuse-side evaluators). Fixing one does not fix the other.

---

### 05 — Dataset
| | |
|---|---|
| **What** | Write down what the agent should handle and what a good answer looks like. |
| **How** | `npm run dataset:seed` → creates `dad-it-support-workshop` with 14 items from `data/seed-dataset.json`. |
| **What it gives** | A fixed, repeatable test set: the foundation for experiments and for catching regressions. |

Item shape:
```json
{
  "id": "dad-001",
  "input": { "messages": [{ "role": "user", "content": "How do I turn Bluetooth on on my iPhone?" }] },
  "expectedOutput": {
    "idealAnswer": "Open Settings, tap Bluetooth, and turn the Bluetooth switch on.",
    "expectedKeywords": ["Settings", "Bluetooth", "switch", "on"]
  },
  "metadata": { "category": "iphone-bluetooth", "difficulty": "easy" }
}
```
- `input` is the same `{ messages }` shape `/api/chat` takes → it feeds straight into `runSupportConversation()`.
- `idealAnswer` → used by the **correctness** judge (06).
- `expectedKeywords` → used by **keyword_overlap** (06).
- `metadata` → slice results by category/difficulty.
- Coverage: Bluetooth, Wi-Fi, photos + WhatsApp, Maps, Messages, out-of-scope (taxes, train booking), limitations (passwords, live location).

Other ways to add items: manual in UI, CSV/JSON upload, **"add to dataset" from a real trace** (best once monitoring flags interesting traces).

**Issues I faced**
- None specific to this step.

---

### 06 — Experiments → see deep dive in §3

### 07 — Evaluate a change → see deep dive in §4

---

## 3. Deep dive — 06 Experiments

### What it is
A **trace** tells me about *one* turn. An **experiment** runs the agent over the **whole dataset** and scores every answer, producing a **run** — a measured baseline of how the current version (prompt + model + code) behaves.

### How we did it
```bash
git checkout checkpoint/06-experiments
npm run dataset:run          # scripts/run-dataset.ts
```

`scripts/run-dataset.ts`, step by step:
1. **Boot OpenTelemetry** (`NodeSDK` + `LangfuseSpanProcessor`), exactly like the server, so the agent's `observe`/`observeOpenAI` spans go to Langfuse.
2. **Load the dataset**: `langfuse.dataset.get(DATASET_NAME)`.
3. **`dataset.runExperiment({...})`**:
   - `runName: "dad-it-support-<ISO timestamp>"` — unique per run so runs never collide.
   - `metadata: { model }` — records which model this run used.
   - `maxConcurrency: 1` — one item at a time (easy to follow; kind to free-tier rate limits).
   - **`task(item)`** — calls the **same** `runSupportConversation()` the web app uses, returns `response.answer`. No parallel "test version" of the app.
   - **`evaluators: [...]`** — two callbacks that run *in my process* right after each `task`:
     - **`keyword_overlap`** (deterministic): fraction of `expectedKeywords` found in the answer (case-insensitive). `0.75` = 3 of 4 keywords. Comment: "Matched 3 of 4 expected keywords."
     - **`correctness`** (LLM-as-a-judge): sends the answer and the `idealAnswer` to the model from `.env` with a **semantic-equivalence** prompt and `response_format: json_object`; expects `{"score": true/false, "reasoning": "..."}` → score `1`/`0` plus the reasoning as a comment.
4. **Print the summary** (`result.format()`) and **flush** everything before exiting.

### What it provides (the offerings)
| Offering | Where in Langfuse | Why it matters |
|---|---|---|
| **Experiment run row** | Datasets → `dad-it-support-workshop` → Experiments | One row per run with average `keyword_overlap` and `correctness` → a baseline number. |
| **Per-item results** | Click into the run | For every item: input, expected output, actual output, both scores, judge reasoning. |
| **Per-item traces** | Trace link on each item | Same shape as production traces, so I can debug *why* an item failed (wrong tool result? skipped tool? prompt issue?). |
| **Scores with comments** | Scores on each trace | The `correctness` comment explains the judge's decision → fast triage. |
| **Run metadata** | Run details | Which model was used; with prompt management, which prompt version each generation used. |
| **Charts** | Dataset chart view | Per-run averages → becomes a trend line once there are more runs. |
| **Console summary** | Terminal | Immediate result without opening the UI. |

### The two evaluators compared
| | `keyword_overlap` | `correctness` |
|---|---|---|
| Type | Deterministic code | LLM-as-a-judge |
| Question | "Did the answer **mention** the expected steps/words?" | "Does the answer **mean** the same as the ideal answer?" |
| Uses | `expectedKeywords` | `idealAnswer` |
| Output | 0.0–1.0 fraction | 0 or 1, plus reasoning |
| Cost/speed | Free, instant | One extra model call per item |
| Strength | Cheap, repeatable, no judge bias | Understands paraphrases; catches wrong or missing facts |
| Weakness | Literal: a good refusal worded differently can score 0 on out-of-scope items | Non-deterministic; only as good as the judge model and prompt |

**When they disagree, read the item.** High keywords + correctness 0 = the right words but a wrong or incomplete meaning. Low keywords + correctness 1 = fine answer, different wording (common on out-of-scope refusals).

### Callback evaluators vs Langfuse Platform evaluators
- **Callback** (what we used): runs in the script, defined in git, scores are there as soon as the run finishes, and **no Langfuse UI setup** is needed. Uses the `.env` model.
- **Platform** (optional bonus, e.g. "Check Correctness"): runs inside Langfuse asynchronously and can be shared across the team, but configuring it needs **existing experiment data** to preview variable mappings (chicken-and-egg before the first run). Uses the **Langfuse LLM Connection**.

### Issues / watch-outs for 06
- The judge needs a model with **JSON mode** — verified working with `gemini-3.5-flash`, `gemini-3.8-flash`, and OpenRouter `openai/gpt-4.1-mini`.
- Free tiers can return **429/503** mid-run → wait and rerun (a new run name is generated each time).
- The script can **exit 0 even if every item failed** → always check that the console prints results, not just SDK errors.
- Changing `OPENAI_MODEL` changes **both** the agent and the judge → keep that in mind when comparing runs.

---

## 4. Deep dive — 07 Evaluate a change

### What it is
Change **one thing**, rerun the **same dataset** with the **same evaluators**, and compare the new run with the 06 baseline. This turns "I think the new prompt is better" into evidence.

### How we did it
1. **Study run 1 first.** Open the low-scoring items and read the answers. Typical finding: the agent improvises on out-of-scope requests instead of refusing cleanly.
2. **Change the prompt** (the lowest-friction lever). The rule added:
   > *If a request is outside iPhone help (taxes, travel booking, anything that needs live account access), say so directly in one short sentence — what you can't help with and what you can — then stop. Do not attempt to answer the request.*
   - **Option A (recommended): Langfuse UI** → Prompts → `dad-it-support-agent` → new version → add the rule → save → promote to the `production` label. The app fetches by label, so the next request uses it with no deploy.
   - **Option B: code** → edit `SYSTEM_PROMPT`, then `npm run prompt:publish`. Or use the built-in variant: `WORKSHOP_PROMPT_VARIANT=gentler npm run prompt:publish`.
3. **Rerun:** `npm run dataset:run` → run 2, scored by the same `keyword_overlap` + `correctness` callbacks.
4. **Compare** in Langfuse: dataset → Experiments tab (both rows with averages) → chart view → **"Compare with"** to see run 1 vs run 2 side by side, item by item.

### What it provides (the offerings)
- **Side-by-side run comparison**: the same item, old answer vs new answer, old scores vs new scores.
- **Average deltas**: did mean `correctness` / `keyword_overlap` go up or down?
- **Per-item improvements and regressions**: the real value. A prompt fix for out-of-scope items might quietly break an in-scope item.
- **Prompt version ↔ run linkage**: each run's generations point to the prompt version they used, so I always know which prompt produced which scores.
- **A permanent baseline**: every future change (model, context, tools, architecture) can be measured against these runs.

### What to look for in the comparison
| Pattern | Meaning | Action |
|---|---|---|
| Out-of-scope items: correctness 0 → 1 | The intended fix worked | ✅ |
| In-scope item: correctness 1 → 0 | **Regression** caused by the change | Read it; refine the rule |
| keyword_overlap drops but correctness holds | Wording changed, meaning didn't | Usually fine; maybe update the keywords |
| Answers get shorter / more refusals overall | The change shifted the agent's scope | Check it isn't refusing valid requests |
| Averages up **and** spot-checked items look right | Evidence to ship | Keep the version on `production` |

### Decision rule
Ship when the averages improve **and** I've read enough individual items to trust that the scores reflect reality. A higher average with a serious regression on an important item is **not** a win.

### Issues / watch-outs for 07
- **Change one variable at a time.** If I change the prompt **and** the model, I can't attribute the difference.
- The judge is an LLM → small swings (±1 item) can be noise. Look at *which* items changed, not just the average.
- Make sure the new prompt version actually carries the **`production`** label, otherwise run 2 still uses the old prompt (check the Prompt badge on a run-2 generation).
- If Langfuse is unreachable, the app silently falls back to the local `SYSTEM_PROMPT` → run 2 might not be testing the new prompt.

---

## 5. Mental model (one paragraph each)

- **Trace = what happened** in one turn (debugging a single case).
- **Monitor (evaluator on live traces) = what should I look at?** (signals at volume).
- **Dataset = what should happen** (written expectations: input + ideal answer + keywords).
- **Experiment = how the current version actually performs** across all expectations (a measured baseline).
- **Evaluation of a change = did my change help or hurt?** (run A vs run B on the same dataset with the same scorers).
- **Prompt management = the cheap lever** that makes change → rerun → compare a minutes-long loop instead of a deploy cycle.

The loop: **production traces → monitors flag the interesting ones → they become dataset items → experiments set a baseline → change one thing → rerun → compare → ship → back to production traces.**

The design choice that makes it work: experiments call the **exact same `runSupportConversation()`** as production, so experiment traces look identical to production traces and the results are trustworthy.

---

## 6. Quick reference

```bash
npm run dev                          # app at http://127.0.0.1:3333 (restart after editing .env!)
npm run prompt:publish               # push SYSTEM_PROMPT to Langfuse (label: production)
WORKSHOP_PROMPT_VARIANT=gentler npm run prompt:publish
npm run langfuse:seed:otel:no-scores # seed production-like traffic (run ONCE)
npm run dataset:seed                 # create dataset + 14 items
npm run dataset:run                  # run experiment + keyword_overlap + correctness
git checkout checkpoint/0X-...       # jump to a module (commit/stash local edits first)
```

| Config | Used by |
|---|---|
| `.env` `OPENAI_*` | The app's agent **and** the step-06/07 `correctness` judge |
| Langfuse **LLM Connections** | Langfuse-side evaluators (04 disagreement judge, optional Platform evaluators) |
| `.env` `LANGFUSE_*` | Traces, prompt fetch, dataset seed, experiment runs |

---

## 7. Python track (FastAPI port, lives in `Python/`)

### Phase 03 — Prompt management (Python)

| | |
|---|---|
| **What** | Move the bot's instructions (the system prompt) out of the code and into Langfuse, where they are versioned and labelled. Fetch the `production` version on each question, and keep the local copy as a fallback. |
| **How** | 5 small edits in `Python/app/support_agent.py` (below), plus `scripts/publish_prompt.py` + `make prompt-publish`, and the lesson `Python/learners/03-prompt-management.md`. |
| **What it gives** | Change the bot's behavior from the Langfuse website with no code edit and no restart (takes effect within ~60 s). Every AI call in a trace shows a **Prompt badge** (`dad-it-support-agent · v2`) naming the exact version it used. If Langfuse fails, the bot still answers. |

#### Background: what a system prompt is

Every question sends OpenAI a list of messages. The first one, the **system prompt**, is the bot's instruction sheet (tone, rules, format):

```
[system]  "You are Dad IT Support Agent. Speak directly to Dad. Use short numbered steps..."
[user]    "How do I turn Bluetooth on?"
```

**Before Phase 03** it was hard-coded (`SYSTEM_PROMPT = """..."""`). Changing one word meant editing code, review, and a restart, and nobody could tell which version produced which answer.

**After Phase 03** it lives in Langfuse → **Prompts**:
- name `dad-it-support-agent`
- every save = a new **version** (v1, v2, v3…)
- the **label** `production` marks the live version. Move the label to change what the app uses.

#### The code changes (`Python/app/support_agent.py`)

**1. Helper that fetches the prompt**

```python
def get_prompt() -> TextPromptClient | None:
    if not is_langfuse_configured():          # no Langfuse keys → don't try
        return None
    try:
        return get_client().get_prompt(env.langfuse_prompt_name,
                                       label=env.langfuse_prompt_label)
    except Exception:                         # Langfuse down, prompt missing, anything
        return None
```

It returns a **prompt object** (text + name + version + id), or `None` if anything goes wrong.

**2. Choose the text (the fallback)**

```python
langfuse_prompt = get_prompt()
system_prompt = langfuse_prompt.prompt if langfuse_prompt else SYSTEM_PROMPT
```

The old `SYSTEM_PROMPT` stays in the file as the spare tyre. If Langfuse is down, keys are missing, or the prompt doesn't exist, the bot still works.

**3. Actually send it**

```python
{"role": "system", "content": system_prompt},   # was: SYSTEM_PROMPT
```

Without this, the app fetches the prompt and then ignores it.

**4. Link each AI call to the prompt version**

```python
response = client.chat.completions.create(
    model=..., messages=transcript, tools=...,
    langfuse_prompt=langfuse_prompt,   # ← new: gives the Prompt badge
)
```

**5. 60-second cache (automatic, no code)**: the SDK remembers the prompt for 60 s, so the app doesn't call Langfuse on every question. That's why an edit takes up to ~1 minute to show up.

**Other files**
- `scripts/publish_prompt.py` + `make prompt-publish` → uploads the local `SYSTEM_PROMPT` as a **new version** with the `production` label (the code alternative to pasting it into the website). `WORKSHOP_PROMPT_VARIANT=gentler make prompt-publish` publishes the softer-tone variant (used in lesson 07).
- `Python/learners/03-prompt-management.md` → the lesson. `Python/README.md` → updated.

#### What "linking" means, and the TS vs Python difference

Langfuse records every OpenAI call as a **generation** (input, output, tokens, time; set up in Phase 02). On its own, a generation doesn't know which prompt version it used. **Linking** adds the note "this call used `dad-it-support-agent` v2". That gives you the badge, the prompt page lists every generation that used it, and later lessons can compare v2 vs v3 answers.

The only difference is **where you hand the prompt to the tracer**:

| | TypeScript | Python |
|---|---|---|
| How tracing is added | Wrap the client: `observeOpenAI(new OpenAI(), ...)` | Swap the import: `from langfuse.openai import OpenAI` (Phase 02) |
| Where the prompt goes | **Once**, when wrapping: `observeOpenAI(client, { langfusePrompt })` | **On each call**: `create(..., langfuse_prompt=langfuse_prompt)` |
| Analogy | Name sticker on the pen: everything written with it is tagged | Stamp on each letter |
| Missing prompt | Needs `langfusePrompt ? { langfusePrompt } : undefined` | Just pass `None`, no `if` needed |

- Python has no wrapping step, so the SDK takes the prompt as an extra argument per call. Our `create(...)` is written **once** inside a loop that runs ~3× per question, so every call is covered. Same result as TS.
- OpenAI never sees `langfuse_prompt`: the Langfuse wrapper reads it and **removes it** before sending the request.
- **Passing `None` is fine.** With the fallback, `langfuse_prompt=None`. The call works normally and the generation is still recorded, just **without a badge**. That's correct, because the local text isn't a Langfuse version.

#### The whole flow

```
Dad asks a question
        │
        ▼
get_prompt() ──► Langfuse: "give me dad-it-support-agent @ production"
        │              │
        │        ✅ got v2  → use v2 text, link generations to v2  (badge shows)
        │        ❌ failed  → use local SYSTEM_PROMPT, no link      (no badge, still answers)
        ▼
OpenAI call(s) with that system prompt  ──►  answer back to Dad
        │
        ▼
Langfuse trace: agent → generations (each with prompt v2 badge) → tool calls
```

**One line:** Phase 03 moved the bot's instructions from the code into Langfuse, where they can be edited and versioned. The app fetches them on each question (falling back to the local copy if that fails), and every AI call in the trace is tagged with the exact prompt version it used.

#### How it was tested

- Live prompt: 1 chat turn → all 3 generations linked to `dad-it-support-agent` **v2**, and the system message sent = the v2 text (not the local one).
- Prompt name that doesn't exist → still answers with the local `SYSTEM_PROMPT`, no badge, no crash (SDK logs one "not found" warning).
- No Langfuse keys → `get_prompt()` returns `None` straight away.
- `make verify-tracing` → still 18/18 checks pass (no regression from Phase 02).
- Publish script tested with the Langfuse call faked (nothing published): `default` = `SYSTEM_PROMPT`, `gentler` adds the tone rules, unknown variant → clear error.

#### Where to check in Langfuse

- Prompt: https://cloud.langfuse.com/project/cmv9cn3sw001uad0j77gbbm8b/prompts/dad-it-support-agent
- Example trace with the badge: https://cloud.langfuse.com/project/cmv9cn3sw001uad0j77gbbm8b/traces/217cea76bd317bcdd8bf257c702c5c1e?observation=77c264523326623c
- Fresh trace: `cd Python && make app`, ask a question at http://127.0.0.1:3333, then Traces → `dad-it-support-chat-turn`.

#### Quick reference (Python)

```bash
cd Python
make app                                              # API :8787 + UI :3333 (restart after code/.env edits, no auto-reload)
make prompt-publish                                   # SYSTEM_PROMPT → new version, label production
WORKSHOP_PROMPT_VARIANT=gentler make prompt-publish   # softer tone variant
make verify-tracing                                   # Phase 02 checks (needs `make api` running)
```

**Watch out for**
- The live v2 prompt in Langfuse is **not** the same text as the local `SYSTEM_PROMPT` (it was edited or a variant was published), so the app answers with v2's text.
- `make prompt-publish` creates a new version **and moves the `production` label**, which changes what the live app uses.
- `.env` wins over the shell: `LANGFUSE_PROMPT_NAME=x make app` does nothing if `.env` sets it. Edit `.env` instead. (`WORKSHOP_PROMPT_VARIANT` isn't in `.env`, so it works from the shell.)
- `Python/` isn't in git: editing it in place overwrote the finished Phase 02 code. Backup of the 02 state: `/private/tmp/claude-501/-Users-devansh-Downloads-langfuse-workshop/ff46c9c1-8443-4204-8011-8bd9556817c6/scratchpad/py-02-final/` (the scratchpad can be cleared on reboot, so copy it somewhere permanent).
