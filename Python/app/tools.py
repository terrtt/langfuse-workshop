"""Tool definitions and executor. Mirrors src/server/tools.ts."""

from typing import Any

from langfuse import get_client, observe

from .support_data import get_support_context, search_guides

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_support_context",
            "description": "Look up Dad's known device setup so the answer stays grounded.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_help_library",
            "description": "Search the local help library for practical step-by-step device instructions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "Dad's practical device question.",
                    }
                },
                "required": ["question"],
                "additionalProperties": False,
            },
        },
    },
]


# The tool takes no arguments, so skip the decorator's empty {"args": [], "kwargs": {}} input.
@observe(name="get_support_context", as_type="tool", capture_input=False)
def get_support_context_tool() -> dict[str, Any]:
    context = get_support_context()
    return {
        "ok": True,
        "context": {
            "id": context["id"],
            "label": context["label"],
            "devices": context["devices"],
            "deviceSummary": context["deviceSummary"],
            "responseStyle": context["responseStyle"],
            "scopeHighlights": context["scopeHighlights"],
            "notableApps": context["notableApps"],
        },
    }


# capture_input=False + an explicit input keeps the tool input as {"question": ...},
# matching the TS trace, instead of the decorator's {"args": ..., "kwargs": ...}.
@observe(name="search_help_library", as_type="tool", capture_input=False)
def search_help_library_tool(question: str) -> dict[str, Any]:
    get_client().update_current_span(input={"question": question})
    guides = search_guides(question)
    return {
        "ok": True,
        "results": [
            {
                "id": guide["id"],
                "title": guide["title"],
                "summary": guide["summary"],
                "steps": guide["steps"],
                "caution": guide.get("caution"),
            }
            for guide in guides
        ],
    }


def execute_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "get_support_context":
        return get_support_context_tool()

    if name == "search_help_library":
        question = args.get("question")
        return search_help_library_tool("" if question is None else str(question))

    return {"ok": False, "error": f"Unsupported tool: {name}"}
