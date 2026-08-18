"""FastAPI server — polls Yahoo, computes recommendations, serves the iPad UI.

Run:  python -m uvicorn src.server:app --host 0.0.0.0 --port 8000

Binding to 0.0.0.0 is what lets the iPad reach it over Tailscale. Nothing here is
authenticated, so do not expose this port to the open internet — Tailscale keeps it
on a private mesh, which is the whole reason we chose it.

MOCK_MODE=1 runs a simulated draft with no Yahoo credentials, so the UI and the
recommendation engine can be exercised end to end before draft day.
"""

from __future__ import annotations

import asyncio
import os
import random
import traceback
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import STATIC_DIR, Settings, load_league_settings, load_rankings
from .draft_state import DraftState, normalize_name
from .recommend import Recommender

MOCK_MODE = os.getenv("MOCK_MODE", "0") == "1"

# MANUAL_MODE is the primary mode for this league. Yahoo denies Fantasy Sports API
# scope to newly created apps, so there is no live pick feed to poll — you enter picks
# as they're announced and everything downstream works unchanged.
MANUAL_MODE = os.getenv("MANUAL_MODE", "0") == "1"

settings = Settings.load()
rankings = load_rankings()
league = load_league_settings()

state = DraftState(
    teams=int(os.getenv("LEAGUE_TEAMS", "10")),
    rounds=int(os.getenv("DRAFT_ROUNDS", "16")),
)

_recommender: Recommender | None = None
_player_lookup: dict[str, dict] = {}
_cache: dict[str, Any] = {
    "recommendations": None,
    "computed_for_pick": None,
    "last_poll": None,
    "poll_error": None,
    "connected": False,
    "news": None,
}
_lock = asyncio.Lock()


def recommender() -> Recommender:
    global _recommender
    if _recommender is None:
        _recommender = Recommender(settings, rankings, league)
    return _recommender


# --------------------------------------------------------------------- polling


async def poll_yahoo() -> None:
    """Pull draft results and fold any new picks into the shared state."""
    from .yahoo_client import YahooClient

    client = YahooClient(settings)

    # Build the player_key -> player map once. Draft results reference players by
    # key only, so without this every pick would be an opaque id.
    global _player_lookup
    if not _player_lookup:
        try:
            for player in await asyncio.to_thread(client.all_players, 300):
                _player_lookup[player["player_key"]] = player
        except Exception as exc:  # noqa: BLE001
            _cache["poll_error"] = f"player list: {exc}"

    picks = await asyncio.to_thread(client.draft_results)
    _cache["connected"] = True

    if len(picks) <= len(state.drafted):
        return

    new = picks[len(state.drafted):]
    for pick in new:
        info = _player_lookup.get(pick["player_key"], {})
        state.drafted.append(
            {
                "pick": pick["pick"],
                "round": pick["round"],
                "team_key": pick["team_key"],
                "player_key": pick["player_key"],
                "name": info.get("name", pick["player_key"]),
                "position": info.get("position", "?"),
                "team": info.get("team", "?"),
            }
        )

    # Infer the draft slot from our own first pick, once we know which team is ours.
    if state.slot is None and state.my_team_key:
        mine = state.my_roster()
        if mine:
            first = min(p["pick"] for p in mine)
            state.slot = ((first - 1) % state.teams) + 1


async def mock_tick() -> None:
    """Simulate a draft locally so the system can be tested without Yahoo."""
    if len(state.drafted) >= state.teams * state.rounds:
        return
    taken = state.drafted_keys
    remaining = [p for p in rankings["players"] if normalize_name(p["name"]) not in taken]
    if not remaining:
        return
    # Other managers pick near the top of the board with some noise.
    choice = random.choice(remaining[: min(6, len(remaining))])
    pick_no = len(state.drafted) + 1
    team_idx = ((pick_no - 1) % state.teams) + 1
    if (pick_no - 1) // state.teams % 2 == 1:
        team_idx = state.teams - team_idx + 1
    state.drafted.append(
        {
            "pick": pick_no,
            "round": (pick_no - 1) // state.teams + 1,
            "team_key": f"mock.t.{team_idx}",
            "player_key": f"mock.p.{choice['rank']}",
            "name": choice["name"],
            "position": choice["pos"],
            "team": choice["team"],
        }
    )
    _cache["connected"] = True


async def refresh_recommendations() -> None:
    """Recompute when the board has moved past what we last computed for."""
    pick = state.next_pick_number
    if _cache["computed_for_pick"] == pick:
        return
    try:
        result = await asyncio.to_thread(recommender().recommend, state, pick, 10)
        _cache["recommendations"] = result
        _cache["computed_for_pick"] = pick
    except Exception as exc:  # noqa: BLE001
        _cache["recommendations"] = {
            "roster_read": "",
            "positional_watch": f"Recommendation engine error: {exc}",
            "recommendations": [],
            "error": "engine",
        }
        traceback.print_exc()


async def poll_loop() -> None:
    while True:
        try:
            async with _lock:
                if MANUAL_MODE:
                    # No external feed. State advances only via /api/manual-pick.
                    _cache["connected"] = True
                elif MOCK_MODE:
                    await mock_tick()
                else:
                    await poll_yahoo()
                _cache["poll_error"] = None

            # Only spend a model call when our pick is close. Recomputing on every
            # pick in the round is wasted latency and tokens.
            until = state.picks_until_my_turn()
            if state.slot is None or until is None or until <= 4:
                async with _lock:
                    await refresh_recommendations()

        except Exception as exc:  # noqa: BLE001
            _cache["poll_error"] = str(exc)
            _cache["connected"] = False

        await asyncio.sleep(settings.poll_interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(poll_loop())
    yield
    task.cancel()


app = FastAPI(title="Fantasy Draft Assistant", lifespan=lifespan)


# ---------------------------------------------------------------------- routes


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


def _fresh_recommendations() -> tuple[dict | None, bool]:
    """Return (recommendations, stale).

    A model call takes ~30s, so after each pick there is a window where the cached
    result predates the current board. Serving it unchanged risks recommending a
    player who was just taken — the one failure that actively costs you a pick. So we
    both flag staleness and defensively strip anyone now drafted, rather than trusting
    the recompute to land before the user looks.
    """
    rec = _cache["recommendations"]
    stale = _cache["computed_for_pick"] != state.next_pick_number
    if not rec or not rec.get("recommendations"):
        return rec, stale

    taken = state.drafted_keys
    filtered = [
        r for r in rec["recommendations"] if normalize_name(r.get("name", "")) not in taken
    ]
    if len(filtered) != len(rec["recommendations"]):
        rec = {**rec, "recommendations": filtered}
    return rec, stale


@app.get("/api/status")
async def status() -> JSONResponse:
    until = state.picks_until_my_turn()
    recommendations, stale = _fresh_recommendations()
    return JSONResponse(
        {
            "mock_mode": MOCK_MODE,
            "manual_mode": MANUAL_MODE,
            "recommendations_stale": stale,
            "connected": _cache["connected"],
            "poll_error": _cache["poll_error"],
            "config_missing": settings.missing(),
            "draft": {
                "teams": state.teams,
                "rounds": state.rounds,
                "slot": state.slot,
                "my_team_key": state.my_team_key,
                "picks_made": state.picks_made,
                "next_pick": state.next_pick_number,
                "current_round": state.current_round,
                "picks_until_my_turn": until,
                "is_my_turn": until == 0,
                "upcoming": state.my_upcoming_picks(3),
            },
            "roster": state.my_roster(),
            "position_counts": state.position_counts(),
            "unmet_starters": state.unmet_starters(),
            "recent_picks": state.drafted[-10:],
            "recommendations": recommendations,
            "news": _cache.get("news"),
        }
    )


@app.post("/api/slot/{slot}")
async def set_slot(slot: int) -> JSONResponse:
    if not 1 <= slot <= state.teams:
        return JSONResponse({"error": f"slot must be 1-{state.teams}"}, status_code=400)
    state.slot = slot
    _cache["computed_for_pick"] = None
    return JSONResponse({"ok": True, "slot": slot})


@app.post("/api/team/{team_key}")
async def set_team(team_key: str) -> JSONResponse:
    """Tell the app which Yahoo team is yours, so roster tracking works."""
    state.my_team_key = team_key
    _cache["computed_for_pick"] = None
    return JSONResponse({"ok": True, "my_team_key": team_key})


@app.get("/api/teams")
async def list_teams() -> JSONResponse:
    if MANUAL_MODE:
        # No Yahoo access; "your team" is implied by which picks you flag as yours.
        return JSONResponse([{"team_key": MANUAL_TEAM_KEY, "name": "My team (manual)"}])
    if MOCK_MODE:
        return JSONResponse(
            [{"team_key": f"mock.t.{i}", "name": f"Mock Team {i}"} for i in range(1, state.teams + 1)]
        )
    try:
        from .yahoo_client import YahooClient

        teams = await asyncio.to_thread(YahooClient(settings).teams)
        return JSONResponse(
            [{"team_key": t.get("team_key", ""), "name": t.get("name", "")} for t in teams]
        )
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": str(exc)}, status_code=500)


MANUAL_TEAM_KEY = "manual.me"


@app.post("/api/manual-pick/{name}")
async def manual_pick(name: str, mine: bool = False) -> JSONResponse:
    """Mark a player drafted. `mine=true` also adds them to your roster.

    In manual mode this is the only way state advances, so the distinction matters:
    without it, roster tracking and need-weighting have nothing to work from.

    Matching is fuzzy on purpose — typing full names on an iPad while a draft clock
    runs is error-prone, so a unique prefix or surname is accepted.
    """
    key = normalize_name(name)
    players = rankings["players"]

    match = next((p for p in players if normalize_name(p["name"]) == key), None)
    if match is None:
        # Fall back to substring matching, but only if it's unambiguous.
        partial = [p for p in players if key and key in normalize_name(p["name"])]
        undrafted = [p for p in partial if normalize_name(p["name"]) not in state.drafted_keys]
        pool = undrafted or partial
        if len(pool) == 1:
            match = pool[0]
        elif len(pool) > 1:
            return JSONResponse(
                {
                    "error": f"'{name}' matches {len(pool)} players — be more specific",
                    "candidates": [p["name"] for p in pool[:6]],
                },
                status_code=409,
            )

    if match is None:
        return JSONResponse({"error": f"'{name}' not on the board"}, status_code=404)
    if normalize_name(match["name"]) in state.drafted_keys:
        return JSONResponse({"ok": True, "note": f"{match['name']} already marked drafted"})

    if mine and state.my_team_key is None:
        state.my_team_key = MANUAL_TEAM_KEY

    state.drafted.append(
        {
            "pick": len(state.drafted) + 1,
            "round": state.current_round,
            "team_key": MANUAL_TEAM_KEY if mine else "manual.other",
            "player_key": f"manual.{match['rank']}",
            "name": match["name"],
            "position": match["pos"],
            "team": match["team"],
        }
    )
    _cache["computed_for_pick"] = None
    return JSONResponse({"ok": True, "marked": match["name"], "mine": mine})


@app.post("/api/undraft/{name}")
async def undraft(name: str) -> JSONResponse:
    """Put a specific player back on the board.

    Distinct from /api/undo, which only reverses the most recent pick. During a live
    draft you often notice a mistake several picks later, so targeted reversal is the
    one that actually gets used.
    """
    key = normalize_name(name)
    before = len(state.drafted)
    removed = [p for p in state.drafted if normalize_name(p.get("name", "")) == key]
    if not removed:
        return JSONResponse({"error": f"'{name}' is not marked drafted"}, status_code=404)

    state.drafted = [p for p in state.drafted if normalize_name(p.get("name", "")) != key]
    # Renumber so pick numbers stay contiguous with the real draft.
    for i, p in enumerate(state.drafted, start=1):
        p["pick"] = i
    _cache["computed_for_pick"] = None
    return JSONResponse(
        {"ok": True, "restored": removed[0]["name"], "removed_count": before - len(state.drafted)}
    )


@app.post("/api/undo")
async def undo_last() -> JSONResponse:
    """Remove the most recent pick. Manual entry means typos, so this is essential."""
    if not state.drafted:
        return JSONResponse({"error": "nothing to undo"}, status_code=400)
    removed = state.drafted.pop()
    _cache["computed_for_pick"] = None
    return JSONResponse({"ok": True, "removed": removed["name"]})


@app.post("/api/news")
async def refresh_news() -> JSONResponse:
    """Get Latest — search for news since the board was built and fold it in.

    Slow (web search plus a model call), so it is user-triggered rather than polled.
    Run it once before the draft; running it mid-draft is fine but costs ~a minute.
    """
    from .news import apply_updates, fetch_updates

    try:
        result = await asyncio.to_thread(fetch_updates, settings, rankings)
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        return JSONResponse({"error": str(exc)}, status_code=500)

    if result.get("error"):
        return JSONResponse(result, status_code=502)

    report = apply_updates(rankings, result.get("updates", []))
    _cache["news"] = {
        "summary": result.get("summary", ""),
        "searched_at": result.get("searched_at"),
        "updates": result.get("updates", []),
        **report,
    }
    # Board changed — force a recompute so recommendations reflect it.
    _cache["computed_for_pick"] = None
    return JSONResponse(_cache["news"])


@app.get("/api/news")
async def last_news() -> JSONResponse:
    return JSONResponse(_cache.get("news") or {"summary": "", "updates": []})


@app.post("/api/refresh")
async def force_refresh() -> JSONResponse:
    async with _lock:
        _cache["computed_for_pick"] = None
        await refresh_recommendations()
    return JSONResponse({"ok": True})


@app.get("/api/board")
async def board() -> JSONResponse:
    """Full board with drafted flags — powers the search/strike UI."""
    taken = state.drafted_keys
    return JSONResponse(
        [
            {**p, "drafted": normalize_name(p["name"]) in taken}
            for p in rankings["players"]
        ]
    )


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
