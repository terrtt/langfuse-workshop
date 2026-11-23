"""Publish the Dad IT Support prompt to Langfuse. Mirrors scripts/publish-prompt.ts.

From python/, run:

    make prompt-publish                                  # the local SYSTEM_PROMPT
    WORKSHOP_PROMPT_VARIANT=gentler make prompt-publish  # the gentler tone variant

Each run creates a new version of LANGFUSE_PROMPT_NAME and moves LANGFUSE_PROMPT_LABEL
(default "production") onto it, so the running app picks it up within 60 seconds.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from langfuse import Langfuse  # noqa: E402

from app.env import env  # noqa: E402  (loads the root .env)
from app.support_agent import SYSTEM_PROMPT  # noqa: E402

PROMPT_VARIANTS = {
    "default": SYSTEM_PROMPT,
    "gentler": f"""{SYSTEM_PROMPT.strip()}

Tone variant:
- Be extra patient and reassuring when Dad seems uncertain.
- Use plain, familiar wording before technical terms.
- Start in-scope final answers with one brief confidence-building sentence.
- If the request is out of scope, say so directly but warmly, then offer the closest iPhone-help next step.
""",
}


def resolve_prompt_variant(variant_name: str) -> tuple[str, str]:
    name = variant_name.strip() or "default"
    if name not in PROMPT_VARIANTS:
        raise SystemExit(
            f'Unsupported WORKSHOP_PROMPT_VARIANT "{variant_name}". '
            f"Supported variants: {', '.join(PROMPT_VARIANTS)}."
        )
    return name, PROMPT_VARIANTS[name]


def main() -> None:
    variant, prompt = resolve_prompt_variant(env.workshop_prompt_variant)

    if not (env.langfuse_public_key and env.langfuse_secret_key):
        raise SystemExit("Langfuse credentials are required to publish prompts.")

    langfuse = Langfuse(
        public_key=env.langfuse_public_key,
        secret_key=env.langfuse_secret_key,
        base_url=env.langfuse_base_url,
    )

    name = env.langfuse_prompt_name or "dad-it-support-agent"
    label = env.langfuse_prompt_label or "production"

    created = langfuse.create_prompt(name=name, type="text", prompt=prompt, labels=[label])
    langfuse.shutdown()

    print(f'Published prompt "{name}" v{created.version} ({variant} variant) with label "{label}".')


if __name__ == "__main__":
    main()
