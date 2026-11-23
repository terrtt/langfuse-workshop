.PHONY: setup app api ui client health context chat chat-invalid verify-tracing prompt-publish

PORT ?= 8787

setup:
	uv sync

# Starts the Python API and the shared React dev UI together (Ctrl+C stops both).
# The UI runs on http://127.0.0.1:3333 and proxies /api to port 8787 (see ../vite.config.ts).
app:
	@test -d ../node_modules || (cd .. && npm install)
	@trap 'kill $$UI_PID 2>/dev/null' EXIT; \
	(cd .. && exec npm run dev:client) & UI_PID=$$!; \
	PORT=$(PORT) uv run python -m app.server

# Python API only (no UI), e.g. for smoke targets or the parity check.
api:
	PORT=$(PORT) uv run python -m app.server

# React dev UI only.
ui:
	cd .. && npm run dev:client

# Builds the shared React client into the repo-root dist/ that the FastAPI server serves.
client:
	cd .. && npm install && npm run build:client

health:
	curl -s http://127.0.0.1:$(PORT)/api/health | python3 -m json.tool

context:
	curl -s http://127.0.0.1:$(PORT)/api/support-context | python3 -m json.tool

chat:
	curl -s -X POST http://127.0.0.1:$(PORT)/api/chat -H "Content-Type: application/json" -d '{"sessionId": "smoke-session", "userId": "dad", "messages": [{"id": "m1", "role": "user", "content": "How do I turn Bluetooth on on my iPhone?", "timestamp": "2026-01-01T00:00:00Z"}]}' | python3 -m json.tool

chat-invalid:
	curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:$(PORT)/api/chat -H "Content-Type: application/json" -d '{"sessionId": "smoke-session", "messages": []}'

# Phase 2 validation: needs `make api` running and Langfuse keys in the root .env.
verify-tracing:
	uv run python scripts/verify_tracing.py --url http://127.0.0.1:$(PORT)

# Phase 3: publish SYSTEM_PROMPT (or WORKSHOP_PROMPT_VARIANT=gentler) to Langfuse with the production label.
prompt-publish:
	uv run python scripts/publish_prompt.py
