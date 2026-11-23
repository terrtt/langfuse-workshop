---
title: "Workshop (Python): Setup"
description: "Set up the Python + FastAPI workshop app with OpenAI and Langfuse credentials, then verify the local Dad IT Support Agent."
---

# 00 Setup (Python)

> This is the Python version of [`docs/learner/00-setup.md`](../../docs/learner/00-setup.md).
> The app, the UI, and the Langfuse project are the same. Only the server
> language and the commands change.

## Goal

Have the Python workshop app running locally with both OpenAI and Langfuse
credentials in place. From here you can skim `01-base-app`, then start building in
`02-tracing`.

> ⚠️ Use **Langfuse Cloud** so you get the features this workshop describes.
> Self-hosted instances may run an older version and won't match the lessons.

## Prerequisites

- **Python 3.11 or newer.** Check with `python3 --version`.
- **[uv](https://docs.astral.sh/uv/)**, the only package manager for the Python
  track. Install it with `brew install uv` or
  `curl -LsSf https://astral.sh/uv/install.sh | sh`, and check with `uv --version`.
- **Node.js `^20.19.0 || >=22.12.0`**, used only for the shared React chat UI.
  Check with `node -v`. An older Node makes `npm install` skip Vite's
  platform binary without an error, and the UI then fails to start later. If you
  upgrade Node after installing, run `npm ci` again in the repo root.

## Starting point

Clone the workshop repository and check out the Python setup checkpoint:

```bash
git clone https://github.com/langfuse/langfuse-workshop.git
cd langfuse-workshop
git checkout checkpoint/py-00-setup
```

`checkpoint/py-00-setup` contains the same untraced app as
`checkpoint/py-01-base-app`. Use it to confirm that your API keys,
dependencies, and local ports work. The Langfuse keys go in now, but traces only
start after you add instrumentation in `02-tracing`.

## Step 1: Get the API keys

1. **OpenAI.** Go to [platform.openai.com](https://platform.openai.com), open
   API Keys, and create one. Copy the `sk-...` value for Step 3.
   - Any OpenAI-compatible provider also works, because the OpenAI SDK reads
     `OPENAI_BASE_URL`. For example, with an OpenRouter key (`sk-or-...`):
     `OPENAI_BASE_URL=https://openrouter.ai/api/v1` and
     `OPENAI_MODEL=openai/gpt-4.1-mini`. The provider must support tool calling.
2. **Langfuse.** Sign up at [langfuse.com](https://langfuse.com) in the **EU
   region**, create a project, and copy the public and secret keys from
   **Settings → API Keys** for Step 3.

## Step 2: Install the Langfuse skill and CLI

Later modules drive Langfuse through a coding agent, which needs the `langfuse`
skill and the Langfuse CLI. This step is the same as on the TypeScript track.

Paste this into your coding agent to install both:

> "Please install the `langfuse` skill from `https://github.com/langfuse/skills/tree/main/skills/langfuse`, and install the Langfuse CLI with `npm install -g langfuse-cli`."

To install them yourself instead:

```bash
# Langfuse CLI
npm install -g langfuse-cli

# Langfuse skill
npx skills add langfuse/skills --skill "langfuse"
```

## Step 3: Configure `.env`

The Python app reads the **repo-root `.env`**, the same file the TypeScript app
uses. Create it in the repo root, not inside `python/`:

```bash
cp .env.example .env
```

Fill in:

```bash
OPENAI_API_KEY=sk-...
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://cloud.langfuse.com
```

Leave the other defaults as they are.

- `OPENAI_MODEL` defaults to `gpt-4.1-mini` on the Python side. The TS app's
  default (`gpt-5.5-2026-04-23`) isn't available to every key. If you copied the
  root `.env.example`, set `OPENAI_MODEL` to a model your key can call.
- Values in `.env` win over values exported in your shell. To change the
  workshop configuration, edit `.env`.
- For a Python-only override, copy `python/.env.example` to `python/.env`.
  Values there win over the root `.env`.

Keep these values in your local `.env` only. Don't paste real API keys into
shared notes, screenshots, or chat messages.

## Step 4: Install and run

```bash
cd python
make setup     # uv sync: creates .venv/ from uv.lock
make app       # Python API on :8787 + React UI on :3333
```

`make app` starts both processes in one terminal. Ctrl+C stops both. The first run
also installs the root npm packages if `node_modules/` is missing.

The Python server does **not** auto-reload. After you edit Python code or `.env`,
press Ctrl+C and run `make app` again. (On the TS track, `npm run dev` restarts
on code changes.)

Open [http://127.0.0.1:3333](http://127.0.0.1:3333) to reach the Dad IT Support
Agent UI.

> `Address already in use` on port 8787 means another server holds the port,
> often the TypeScript `npm run dev`. Stop it first. Both apps use 8787 for the
> API and 3333 for the UI.

## Step 5: Confirm what you see

You should see the **Dad IT Support Agent** chat:

- the Specs mascot at the top
- a greeting from Specs
- suggestion chips below the greeting
- the iPhone panel on the right ("Dad" and the iPhone 15 details)

![How Specs handles a ticket: one agent, two tools, one model, each hop an observation in the trace.](../../docs/images/specs_illustration.png)

## How to verify you are done

- `make app` is running and the UI loads at `http://127.0.0.1:3333`.
- The browser shows the Specs greeting, not an error.
- Sending one of the suggestion chips returns a real iPhone answer from the model.

You can also check from a second terminal, inside `python/`:

```bash
make health   # {"ok": true, "provider": "openai", "tracingConfigured": false}
make chat     # a Bluetooth answer with numbered steps and usedTools
```

## End state

Your environment is ready. Skim [`01-base-app`](01-base-app.md) for a tour of the
app, then go to [`02-tracing`](02-tracing.md) for the first code changes.
