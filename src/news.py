"""Live news refresh — the "Get Latest" button.

Published ranking boards are built days or weeks before you draft and are stale the
moment a hamstring goes. This uses Claude's server-side web search to pull current
injury and depth-chart news and fold it into the board as risk flags.

Deliberately conservative in what it will do:

  - It only ever adjusts players already on the board. It cannot invent new ones,
    because a name the recommender has never scored is not actionable mid-draft.
  - It downgrades and flags; it does not promote. Good news ("cleared to practice")
    clears an existing flag rather than pushing a player up the board, since hype is
    far noisier than injury reports.
  - Every change carries its source URL, so a surprising downgrade can be checked
    rather than taken on faith.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import anthropic

from .config import Settings
from .draft_state import normalize_name

NEWS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": "Two or three sentences on what changed since the board was built. Say plainly if nothing material has.",
        },
        "updates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Player name as commonly written."},
                    "issue": {"type": "string", "description": "The injury, suspension, or role change, briefly."},
                    "status": {
                        "type": "string",
                        "enum": [
                            "out_for_season",
                            "extended_absence",
                            "pup_multi_week",
                            "doubtful_week1",
                            "week_to_week",
                            "short_term_expected_ready",
                            "recovery_on_track",
                            "minor",
                            "cleared",
                        ],
                        "description": "Use 'cleared' when a previously injured player is now fully healthy.",
                    },
                    "source_url": {"type": "string", "description": "URL of the report this came from."},
                    "detail": {"type": "string", "description": "Draft implication in one line. Empty string if none."},
                },
                "required": ["name", "issue", "status", "source_url", "detail"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "updates"],
    "additionalProperties": False,
}

PENALTIES = {
    "out_for_season": 999,
    "extended_absence": 60,
    "pup_multi_week": 40,
    "doubtful_week1": 30,
    "week_to_week": 15,
    "short_term_expected_ready": 8,
    "recovery_on_track": 5,
    "minor": 2,
    "cleared": 0,
}


def fetch_updates(settings: Settings, rankings: dict) -> dict:
    """Search for news since the board was built and return structured updates."""
    client = (
        anthropic.Anthropic(api_key=settings.anthropic_api_key)
        if settings.anthropic_api_key
        else anthropic.Anthropic()
    )

    known = ", ".join(p["name"] for p in rankings["players"][:200])
    built = rankings["meta"].get("revised_on", rankings["meta"].get("built_on", "recently"))

    prompt = f"""Today is {date.today().isoformat()}. Search the web for the most recent NFL
injury news, roster moves, and depth-chart changes affecting 2026 fantasy football draft value.

This draft board was last updated {built}. I need to know what has changed since then that
would alter how these players should be drafted.

Prioritise, in this order:
1. Players newly ruled out for the season or facing extended absences
2. New injuries from training camp or preseason games
3. Players previously injured who are now cleared (use status "cleared")
4. Depth-chart changes that materially move a player's projected workload

Only report players from this board — anyone else is not actionable for this draft:

{known}

Report only genuine changes with a source. If nothing material has changed, return an
empty updates list and say so in the summary. Do not report routine practice notes,
speculation, or beat-writer opinion as if it were news."""

    response = client.messages.create(
        model=settings.model,
        max_tokens=8000,
        thinking={"type": "adaptive"},
        output_config={
            "effort": "medium",
            "format": {"type": "json_schema", "schema": NEWS_SCHEMA},
        },
        tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 8}],
        messages=[{"role": "user", "content": prompt}],
    )

    if response.stop_reason == "refusal":
        return {"summary": "The model declined this request.", "updates": [], "error": "refusal"}

    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        return {
            "summary": "Could not parse the news response.",
            "updates": [],
            "error": "parse_error",
        }

    result["searched_at"] = date.today().isoformat()
    result["usage"] = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }
    return result


def apply_updates(rankings: dict, updates: list[dict]) -> dict:
    """Fold updates into the board in place. Returns a report of what changed."""
    by_key = {normalize_name(p["name"]): p for p in rankings["players"]}
    applied, unknown, dropped = [], [], []

    for u in updates:
        player = by_key.get(normalize_name(u.get("name", "")))
        if player is None:
            unknown.append(u.get("name", "?"))
            continue

        status = u.get("status", "")
        if status == "cleared":
            if player.pop("injury", None):
                applied.append(f"{player['name']}: flag cleared")
            continue

        if status == "out_for_season":
            player["injury"] = {
                "issue": u.get("issue", ""),
                "status": status,
                "penalty": 999,
                "detail": u.get("detail") or "Out for the season — do not draft.",
                "source_url": u.get("source_url", ""),
                "from_news": True,
            }
            dropped.append(player["name"])
            applied.append(f"{player['name']}: OUT FOR SEASON")
            continue

        player["injury"] = {
            "issue": u.get("issue", ""),
            "status": status,
            "penalty": PENALTIES.get(status, 0),
            "detail": u.get("detail", ""),
            "source_url": u.get("source_url", ""),
            "from_news": True,
        }
        applied.append(f"{player['name']}: {status}")

    return {"applied": applied, "unknown_players": unknown, "out_for_season": dropped}
