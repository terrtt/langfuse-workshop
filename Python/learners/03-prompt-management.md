---
title: "Workshop (Python): Prompt Management with Langfuse"
description: "Move the Python agent's system prompt into Langfuse, fetch the production prompt at runtime, and link every traced generation to its prompt version."
---

# 03 Prompt Management (Python)

> This is the Python version of [`docs/learner/03-prompt-management.md`](../../docs/learner/03-prompt-management.md).
> The goal, the Langfuse UI steps, and the resulting Prompt badge are the same, and
> the screenshots come from the shared lesson.

## Starting point

```bash
git checkout checkpoint/py-02-tracing
cd python
make setup
```

You have a working traced app. The system prompt is a constant called
`SYSTEM_PROMPT` in `app/support_agent.py`, and it is sent directly as the system
message.

In this chapter we move that prompt into Langfuse so it is versioned and editable in
the UI, and we fetch it back on each request. The local constant stays in the file
as a fallback for when Langfuse can't be reached.

> On the Python track, `checkpoint/py-03-prompt-management` holds the **finished**
> result of this chapter. If you get stuck, compare your files with that tag.

Make sure the repo-root `.env` has:

```bash
LANGFUSE_PROMPT_NAME=dad-it-support-agent
LANGFUSE_PROMPT_LABEL=production
```

## Why manage prompts

When the system prompt lives in code, every prompt change is a code change: pull
request, review, build, deploy. With Langfuse prompt management, the prompt lives in
Langfuse, where it is versioned, labelled, and editable in the UI, and the app
fetches it at request time. Non-engineers can iterate on prompts, changes ship
without a release, and every version is kept and linked to the traces it produced.

Learn more in the [Langfuse prompts docs](https://langfuse.com/docs/prompt-management/overview).

## Goal

Two steps:

1. **Publish the system prompt to Langfuse**, so a versioned copy lives there.
2. **Fetch it back at request time**, and link each OpenAI generation to the
   version that produced it.

### TypeScript to Python at a glance

| TypeScript | Python (Langfuse SDK v5) |
| --- | --- |
| `const langfuse = new LangfuseClient()` | `get_client()`, the client `app/tracing.py` already created |
| `langfuse.prompt.get(name)` | `get_client().get_prompt(name, label=...)` |
| `langfusePrompt?.prompt ?? SYSTEM_PROMPT` | `langfuse_prompt.prompt if langfuse_prompt else SYSTEM_PROMPT` |
| `observeOpenAI(client, { langfusePrompt })` | `client.chat.completions.create(..., langfuse_prompt=langfuse_prompt)` |
| `npm run prompt:publish` | `make prompt-publish` |

## Step 1: Publish the prompt (Langfuse UI)

The most direct way to create a prompt is to add it by hand in the UI. Your team
will use the same workflow for every future change.

1. In Langfuse, open **Prompts → New prompt**.
2. **Name** it `dad-it-support-agent`, matching `LANGFUSE_PROMPT_NAME` in your `.env`.
3. Set **Type** to `text`.
4. **Paste** the text of `SYSTEM_PROMPT` from `app/support_agent.py`, without the
   surrounding `"""` quotes.
5. **Label** the version `production`, matching `LANGFUSE_PROMPT_LABEL` in your `.env`.
6. **Save**.

![Creating the dad-it-support-agent prompt in Langfuse.](../../docs/images/prompt-management/03-prompt-management-new-prompt-form.png)

> 💡 *Alternative: publish with a script.* `scripts/publish_prompt.py` pushes the
> `SYSTEM_PROMPT` constant to Langfuse and labels it `production`. Run it from
> `python/`:
>
> ```bash
> make prompt-publish
> ```
>
> The result is the same. Each run creates a **new version** and moves the
> `production` label onto it.

## Step 2: Fetch the prompt from Langfuse

All edits are in `app/support_agent.py`.

**1. Add the imports.** Add `TextPromptClient` with the other third-party imports,
and add `is_langfuse_configured` to the existing `.env` import:

```python
from langfuse.model import TextPromptClient

from .env import env, is_langfuse_configured   # add is_langfuse_configured
```

`get_client` is already imported from `langfuse` since `02-tracing`.

**2. Add a `get_prompt` helper** above `_to_openai_messages`. It fetches the prompt
from Langfuse and returns `None` on any failure, so the chat can fall back to the
local `SYSTEM_PROMPT`:

```python
def get_prompt() -> TextPromptClient | None:
    """Fetch the managed prompt from Langfuse, or None so the caller falls back to SYSTEM_PROMPT."""
    if not is_langfuse_configured():
        return None
    try:
        # Cached by the SDK for 60 seconds, so this is not a network call on every turn.
        return get_client().get_prompt(env.langfuse_prompt_name, label=env.langfuse_prompt_label)
    except Exception:  # noqa: BLE001 - any failure means "use the local prompt"
        return None
```

You don't need a new client. `get_client()` returns the one `init_tracing()`
created in `02-tracing`.

**3. Use it in `_run_support_conversation_inner`.** At the top of the function,
after `context = get_support_context()`, fetch the prompt and fall back to the local
constant if the fetch returned `None`:

```python
    langfuse_prompt = get_prompt()
    system_prompt = langfuse_prompt.prompt if langfuse_prompt else SYSTEM_PROMPT
```

**4. Send `system_prompt` as the system message.** A few lines below, find this
line in the transcript:

```python
        {"role": "system", "content": SYSTEM_PROMPT},
```

and change it to:

```python
        {"role": "system", "content": system_prompt},
```

Without this change, the model keeps receiving the local constant. The Prompt badge
from the next step would still appear, but editing the prompt in Langfuse would have
no effect on the answers.

**5. Pass `langfuse_prompt` to the OpenAI call**, so the generation is linked to the
published prompt version. Add one argument to the existing
`client.chat.completions.create(...)` call:

```python
        response = client.chat.completions.create(
            model=env.openai_model,
            messages=transcript,
            tools=TOOL_DEFINITIONS,
            tool_choice="auto",
            # Links this generation to the prompt version. None (the fallback) links nothing.
            langfuse_prompt=langfuse_prompt,
        )
```

Three things to notice:

- The `OpenAI` client from `langfuse.openai` didn't change. It is the same drop-in
  replacement from `02-tracing`. `langfuse_prompt` is an extra argument that the
  Langfuse wrapper reads and removes before the request goes to OpenAI.
- The local `SYSTEM_PROMPT` constant stays in the file as the fallback. If Langfuse is
  misconfigured or the prompt isn't published yet, the chat keeps working. That turn
  just won't carry the Prompt badge.
- Passing `langfuse_prompt` is what gives every generation the **Prompt** badge,
  which links back to the exact published version.

> **Python difference:** in TypeScript the prompt is attached once, when you wrap the
> client: `observeOpenAI(client, { langfusePrompt })`. In Python, you pass it on each
> `create(...)` call. Passing `None` is fine: the generation is simply not linked.

## Verify

Restart the server so it picks up the code change (the Python server doesn't
auto-reload):

```bash
make app
```

Ask one question, then in Langfuse:

- Open the trace and click an `OpenAI-generation`. It should show a **Prompt** badge
  linking to `dad-it-support-agent` at the version you published.
- Open `dad-it-support-agent` in the Prompts view. Your trace appears in the list of
  generations that used the prompt.

![A traced generation with the Prompt badge in the top-right linking back to dad-it-support-agent · v1.](../../docs/images/prompt-management/03-prompt-management-prompt-badge.png)

To see that the app really uses the Langfuse copy, edit the prompt in Langfuse and
save it as a new `production` version. Within about 60 seconds (the SDK's cache
time), new answers follow the new version, and the badge shows the new version
number. You don't need to restart anything.

## Python-only notes

- **`.env` wins over your shell.** `LANGFUSE_PROMPT_NAME=other make app` has no
  effect if `.env` already sets `LANGFUSE_PROMPT_NAME`. Edit `.env` instead. The
  publish script's `WORKSHOP_PROMPT_VARIANT` is not in `.env`, so
  `WORKSHOP_PROMPT_VARIANT=gentler make prompt-publish` works from the shell.
- **A missing prompt logs one warning.** If the prompt doesn't exist yet, the SDK
  logs a `Prompt '...' not found` warning and the app uses `SYSTEM_PROMPT`. Publish
  the prompt (Step 1) to make it go away.
- **Without Langfuse keys,** `get_prompt()` returns `None` straight away and the app
  runs on the local prompt, untraced, as in `02-tracing`.

## Wrap-up

Prompt management closes the loop between traces and prompts. Every prompt version is
kept, every generation knows which version produced it, and you can change prompts
without deploying code.

The [**Langfuse skill**](https://github.com/langfuse/skills) (`/langfuse`) sets up
prompt management in line with Langfuse best practices for you. This walkthrough
shows what it does under the hood.

## End state

This is the starting point for `04-monitoring`.
