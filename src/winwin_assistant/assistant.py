"""One conversational turn against the OpenAI Responses API.

Usage:
    export OPENAI_API_KEY=...        # never commit keys; see .env.example
    python -m winwin_assistant.assistant "Going to Haarlem 15-18 Aug, solo, quiet boutique hotel"
"""

from __future__ import annotations

import json
import os
import sys
from datetime import date
from pathlib import Path

from .catalog import load_catalog
from .inventory import MockInventory
from .state import SearchState
from .tools import ToolRouter

ROOT = Path(__file__).resolve().parents[2]
CONFIG = json.loads((ROOT / "assistant" / "config.json").read_text())
INSTRUCTIONS = (ROOT / "assistant" / "system_prompt.md").read_text()
TOP_FILTER_CATEGORIES = {"price", "rating", "style", "room", "beds", "bathroom", "connectivity", "meals", "pets",
                         "parking", "pool", "wellness", "accessibility"}


def top_filters(catalog, limit: int = 150) -> list[str]:
    ids = [f"{f['id']} | {f['label']}" for f in catalog.filters if f["category"] in TOP_FILTER_CATEGORIES]
    return ids[:limit]


def run_turn(user_message: str, state: SearchState, history: list[dict], today: date,
             variant: str = "A", locale: str = "en-NL") -> tuple[dict, SearchState, list[dict]]:
    from openai import OpenAI  # imported lazily so tests run without the SDK

    client = OpenAI()  # reads OPENAI_API_KEY from the environment
    catalog = load_catalog()
    router = ToolRouter(catalog, MockInventory(catalog), today)
    common, params = CONFIG["common"], {k: v for k, v in CONFIG["variants"][variant].items() if not k.startswith("_")}

    context = {"today": today.isoformat(), "timezone": "Europe/Amsterdam", "user_locale": locale,
               "currency": state.currency, "current_state": state.to_dict(), "top_filters": top_filters(catalog)}
    items = history + [
        {"role": "developer", "content": "Runtime context:\n" + json.dumps(context, ensure_ascii=False)},
        {"role": "user", "content": user_message[: common["safety"]["max_user_message_chars"]]},
    ]
    fmt = CONFIG["response_format"]
    text = {**params.pop("text", {}), "format": {k: fmt[k] for k in ("type", "name", "strict", "schema")}}
    if "reasoning" in params:
        # store=false: reasoning items must travel back encrypted between tool rounds
        params["include"] = ["reasoning.encrypted_content"]
    for _ in range(common["max_tool_rounds"] + 1):
        resp = client.responses.create(
            instructions=INSTRUCTIONS, input=items, tools=CONFIG["tools"],
            tool_choice=common["tool_choice"], parallel_tool_calls=common["parallel_tool_calls"],
            max_output_tokens=common["max_output_tokens"], store=common["store"],
            prompt_cache_key=common["prompt_cache_key"], metadata=common["metadata"] | {"variant": variant},
            text=text, **params,
        )
        calls = [o for o in resp.output if o.type == "function_call"]
        if not calls:
            reply = json.loads(resp.output_text)
            # keep only user/assistant text in history; runtime context is re-injected fresh every turn
            history = history + [{"role": "user", "content": user_message},
                                 {"role": "assistant", "content": reply["message"]}]
            return reply, state, history[-24:]
        items += resp.output
        for call in calls:
            args = json.loads(call.arguments)
            if call.name == "update_search":
                state, result = router.update_search(state, args)
            elif call.name == "search_filter_catalog":
                result = router.search_filter_catalog(args)
            else:
                result = {"error": f"unknown tool {call.name}"}
            items.append({"type": "function_call_output", "call_id": call.call_id,
                          "output": json.dumps(result, ensure_ascii=False)})
    raise RuntimeError("tool loop did not converge")


if __name__ == "__main__":
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("Set OPENAI_API_KEY in your environment (see .env.example).")
    reply, new_state, _ = run_turn(" ".join(sys.argv[1:]), SearchState(), [], date.today())
    print(json.dumps({"reply": reply, "state": new_state.to_dict()}, indent=2, ensure_ascii=False))
