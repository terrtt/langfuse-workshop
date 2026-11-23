"""Langfuse tracing setup. Mirrors the NodeSDK + LangfuseSpanProcessor wiring in src/server/index.ts.

The Langfuse Python SDK is built on OpenTelemetry: creating the client registers a
span processor that batches finished spans and exports them over OTLP/HTTP to
LANGFUSE_BASE_URL in the background.
"""

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

    # Registers the client that observe(), propagate_attributes() and the OpenAI wrapper use.
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
