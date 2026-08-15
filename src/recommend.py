"""Recommendation engine — Claude Opus 5.

Prompt layout is deliberate and load-bearing for cost/latency:

    [ system: league rules + strategy + full board ]   <- stable, cached
    [ user:   current draft state                  ]   <- volatile, small

Everything stable sits in the cached prefix, so each in-draft call only pays full
price for the small state delta plus the output. Do not interpolate anything
per-request (timestamps, pick counts, UUIDs) into the system block — a single byte
of drift there invalidates the cache and every later call pays full freight.
"""

from __future__ import annotations

import json
from typing import Any

import anthropic

from .config import Settings
from .draft_state import DraftState, candidate_pool

RECOMMENDATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "roster_read": {
            "type": "string",
            "description": "One or two sentences on the shape of the roster so far and what it still needs.",
        },
        "positional_watch": {
            "type": "string",
            "description": "Any position run in progress or scarcity cliff approaching. Empty string if nothing notable.",
        },
        "recommendations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "position": {"type": "string"},
                    "team": {"type": "string"},
                    "why": {
                        "type": "string",
                        "description": "One line. The specific case for taking this player at this pick.",
                    },
                    "ceiling_case": {
                        "type": "string",
                        "description": "Short. The league-winning outcome if this hits.",
                    },
                    "risk": {
                        "type": "string",
                        "description": "Short. The main way this pick disappoints.",
                    },
                },
                "required": ["name", "position", "team", "why", "ceiling_case", "risk"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["roster_read", "positional_watch", "recommendations"],
    "additionalProperties": False,
}


def build_system_prompt(rankings: dict, league: dict) -> str:
    """Stable prefix. Must be byte-identical across calls to stay cached."""
    meta = rankings["meta"]
    scoring = league["scoring"]
    strategy = meta.get("league_specific_strategy", {})

    board_lines = []
    for p in rankings["players"]:
        bye = p.get("bye")
        bye_txt = f"bye {bye}" if bye else "bye ?"
        note = f" — {p['note']}" if p.get("note") else ""
        board_lines.append(
            f"{p['rank']}. {p['name']} ({p['pos']}, {p['team']}, {bye_txt}, tier {p['tier']}){note}"
        )
    board = "\n".join(board_lines)

    return f"""You are a fantasy football draft advisor for one specific league. Your job is to
recommend the best available picks at each turn, ranked by upside and weighted by roster need.

## The league — read this carefully, it is unusual

League: {league['league_identity']['league_name']} (Yahoo #{league['league_identity']['league_id']})
Format: {meta['format_basis']}
Teams: {league['league_identity'].get('teams_in_2025', 10)}
Draft: {league['draft'].get('rounds', 16)}-round snake

### Scoring — STANDARD, NOT PPR
Receptions are worth {scoring['receiving']['reception']} points. This is the single most important
fact about this league. Receiving yards are {scoring['receiving']['yards_per_point']} yards per point
and receiving TDs are {scoring['receiving']['touchdown']}.
Passing: {scoring['passing']['yards_per_point']} yards/point, {scoring['passing']['touchdown']} per TD,
{scoring['passing']['interception']} per INT.
Rushing: {scoring['rushing']['yards_per_point']} yards/point, {scoring['rushing']['touchdown']} per TD.
Fumbles lost: {scoring['misc']['fumble_lost']}.

Consequences you must apply:
- Slot receivers and pass-catching backs are systematically overvalued by public rankings, which are almost always PPR.
- Volume rushers and touchdown-dependent players are undervalued relative to those rankings.
- Tight ends lose the most as a position group.
- Rushing quarterbacks keep an edge because rushing TDs are worth 6 while passing TDs are worth 4.

### Roster
Starters: {', '.join(league['roster']['starters'])}
Bench: {league['roster']['bench']}. Only two WR slots and two RB slots plus one W/R/T flex.

### Strategy for THIS league
- {strategy.get('draft_for_ceiling', '')}
- {strategy.get('shallow_lineup', '')}
- {strategy.get('stream_k_and_def', '')}

Do not recommend kickers or defenses. Unlimited acquisitions and rolling waivers make them
free to stream weekly; spending draft capital there is a mistake in this league.

## The rankings board

This board has already been adjusted from PPR to standard scoring. Rank is the standard-scoring
rank; where a player moved substantially the note explains why. Tier matters more than exact rank —
players within a tier are close to interchangeable, and the gap between tiers is where real value
is won or lost.

{board}

## How to respond

Rank candidates by ceiling first, then tilt for roster need. This league sends 8 of 10 teams to
the playoffs, so a safe floor is nearly worthless — the objective is a roster that can win in
weeks 15 through 17, not one that reliably goes 8-6.

Be concrete and specific. "Good value here" is useless; say what the actual case is. Keep each
field to the length asked for. If a genuine position run is underway or a tier is about to empty,
say so plainly in positional_watch — that is often more actionable than the player list itself.

Never recommend a player listed as already drafted. Only recommend players from the candidate
list supplied in the user message."""


def build_user_prompt(state: DraftState, pool: list[dict], count: int, pick_number: int) -> str:
    """Volatile suffix — everything that changes per call lives here."""
    roster = state.my_roster()
    roster_txt = (
        "\n".join(
            f"  - {p['name']} ({p.get('position', '?')}, {p.get('team', '?')})" for p in roster
        )
        or "  (empty — this is your first pick)"
    )

    counts = state.position_counts()
    counts_txt = ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())) or "none yet"

    recent = state.drafted[-12:]
    recent_txt = (
        "\n".join(
            f"  {p.get('pick', '?')}. {p['name']} ({p.get('position', '?')})" for p in recent
        )
        or "  (none yet)"
    )

    pool_txt = "\n".join(
        f"  - {p['name']} ({p['pos']}, {p['team']}, tier {p['tier']}, board rank {p['rank']}"
        + (f", falling {p['falls_by']} spots past rank" if p.get("falls_by") else "")
        + ")"
        for p in pool
    )

    until = state.picks_until_my_turn()
    turn_txt = (
        "It is YOUR PICK right now."
        if until == 0
        else f"Your next pick is in {until} picks." if until is not None
        else "Draft slot not set."
    )

    return f"""## Current draft state

Overall pick: {pick_number} (round {state.current_round})
Your slot: {state.slot or 'unknown'}
{turn_txt}

Your roster ({counts_txt}):
{roster_txt}

Unfilled starting slots: {state.unmet_starters() or 'none — all starters covered'}

Last picks made:
{recent_txt}

## Candidates still available

{pool_txt}

Return exactly {count} recommendations, best first, drawn only from the candidate list above."""


class Recommender:
    def __init__(self, settings: Settings, rankings: dict, league: dict):
        self.settings = settings
        self.rankings = rankings
        self.league = league
        # Pass the key only if we actually have one. Otherwise let the SDK resolve
        # credentials itself (ANTHROPIC_API_KEY in the shell, an `ant auth login`
        # profile, etc.) — that way the key never has to be written to a file.
        self.client = (
            anthropic.Anthropic(api_key=settings.anthropic_api_key)
            if settings.anthropic_api_key
            else anthropic.Anthropic()
        )
        self._system = build_system_prompt(rankings, league)

    def recommend(
        self, state: DraftState, pick_number: int | None = None, count: int = 10
    ) -> dict:
        pick = pick_number or state.next_pick_number
        pool = candidate_pool(self.rankings, state, pick)

        if not pool:
            return {
                "roster_read": "",
                "positional_watch": (
                    "The ranked board is exhausted at this pick. Beyond roughly board rank 100 "
                    "there is no ranked data — switch to autodraft or extend the board."
                ),
                "recommendations": [],
                "board_exhausted": True,
            }

        pool = pool[: max(count * 2, 20)]

        response = self.client.messages.create(
            model=self.settings.model,
            max_tokens=8000,
            thinking={"type": "adaptive"},
            output_config={
                "effort": self.settings.effort,
                "format": {"type": "json_schema", "schema": RECOMMENDATION_SCHEMA},
            },
            system=[
                {
                    "type": "text",
                    "text": self._system,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[
                {
                    "role": "user",
                    "content": build_user_prompt(state, pool, count, pick),
                }
            ],
        )

        if response.stop_reason == "refusal":
            return {
                "roster_read": "",
                "positional_watch": "The model declined to respond to this request.",
                "recommendations": [],
                "error": "refusal",
            }

        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            return {
                "roster_read": "",
                "positional_watch": "Could not parse the model response.",
                "recommendations": [],
                "error": "parse_error",
                "raw": text[:500],
            }

        result["usage"] = {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "cache_read": getattr(response.usage, "cache_read_input_tokens", 0),
            "cache_write": getattr(response.usage, "cache_creation_input_tokens", 0),
        }
        result["board_exhausted"] = False
        return result
