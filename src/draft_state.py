"""Snake-draft math, roster tracking, and board availability.

Name matching deserves a note: Yahoo and the rankings board disagree on suffixes
and punctuation ("James Cook III" vs "James Cook", "Ja'Marr" vs "JaMarr"). All
matching goes through normalize_name so those differences don't silently drop a
player from the drafted set — which would make the engine recommend someone who
is already gone.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}

# Starting lineup for this league: QB, WR, WR, RB, RB, TE, W/R/T, K, DEF
STARTER_REQUIREMENTS = {"QB": 1, "RB": 2, "WR": 2, "TE": 1}
FLEX_POSITIONS = {"RB", "WR", "TE"}

# What a sensible 15-pick roster looks like. Used only for need-weighting, not as a rule.
TARGET_COUNTS = {"QB": 2, "RB": 5, "WR": 5, "TE": 2}


def normalize_name(name: str) -> str:
    """Collapse a player name to a comparable key."""
    text = unicodedata.normalize("NFKD", name)
    text = text.encode("ascii", "ignore").decode()
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", "", text)
    parts = [p for p in text.split() if p and p not in SUFFIXES]
    return " ".join(parts)


def snake_pick_number(round_num: int, slot: int, teams: int) -> int:
    """Overall pick number for a given round and draft slot in a snake draft."""
    if round_num % 2 == 1:
        return (round_num - 1) * teams + slot
    return round_num * teams - slot + 1


def picks_for_slot(slot: int, teams: int, rounds: int) -> list[tuple[int, int]]:
    """[(round, overall_pick), ...] for every pick this slot owns."""
    return [(r, snake_pick_number(r, slot, teams)) for r in range(1, rounds + 1)]


@dataclass
class DraftState:
    teams: int = 10
    rounds: int = 16
    slot: int | None = None
    drafted: list[dict] = field(default_factory=list)  # {name, position, team, pick, team_key}
    my_team_key: str | None = None
    targets: list[str] = field(default_factory=list)  # players you specifically want

    # Where the draft actually is, when that differs from what you've entered.
    #
    # In a live room you will miss picks — you're talking, someone drafts fast, you
    # enter two out of order. Inferring position from entry count then makes the app
    # think it is earlier than it is and it will not tell you you're on the clock.
    # Setting this re-syncs everything without needing to backfill who was taken.
    #
    # It also fixes the candidate pool: the pool excludes anyone ranked well above the
    # current pick, so a correct pick number filters out players who are surely gone
    # even when you never entered them.
    current_pick_override: int | None = None

    # ------------------------------------------------------------- derived

    @property
    def picks_made(self) -> int:
        return len(self.drafted)

    @property
    def next_pick_number(self) -> int:
        if self.current_pick_override is not None:
            return self.current_pick_override
        return self.picks_made + 1

    @property
    def is_synced_manually(self) -> bool:
        return self.current_pick_override is not None

    @property
    def current_round(self) -> int:
        return (self.picks_made // self.teams) + 1

    @property
    def drafted_keys(self) -> set[str]:
        return {normalize_name(p["name"]) for p in self.drafted if p.get("name")}

    def my_roster(self) -> list[dict]:
        if self.my_team_key:
            return [p for p in self.drafted if p.get("team_key") == self.my_team_key]
        return []

    def position_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for player in self.my_roster():
            pos = (player.get("position") or "").upper()
            counts[pos] = counts.get(pos, 0) + 1
        return counts

    def my_upcoming_picks(self, limit: int = 3) -> list[tuple[int, int]]:
        """Next few (round, overall_pick) pairs this slot owns."""
        if self.slot is None:
            return []
        upcoming = [
            (r, p)
            for r, p in picks_for_slot(self.slot, self.teams, self.rounds)
            if p >= self.next_pick_number
        ]
        return upcoming[:limit]

    def picks_until_my_turn(self) -> int | None:
        upcoming = self.my_upcoming_picks(limit=1)
        if not upcoming:
            return None
        return upcoming[0][1] - self.next_pick_number

    def is_my_turn(self) -> bool:
        return self.picks_until_my_turn() == 0

    # -------------------------------------------------------------- needs

    def unmet_starters(self) -> dict[str, int]:
        """How many starting slots remain unfilled, by position."""
        counts = self.position_counts()
        gaps = {}
        for pos, required in STARTER_REQUIREMENTS.items():
            shortfall = required - counts.get(pos, 0)
            if shortfall > 0:
                gaps[pos] = shortfall
        return gaps

    def need_multiplier(self, position: str) -> float:
        """Weighting applied to a candidate's upside score.

        Ceiling drives the ranking; this only tilts between players of comparable
        upside so the roster doesn't end up structurally broken.
        """
        pos = position.upper()
        if pos in {"K", "DEF", "DST"}:
            # Unlimited waivers make these freely streamable — never spend a real pick.
            return 0.05

        count = self.position_counts().get(pos, 0)
        required = STARTER_REQUIREMENTS.get(pos, 0)
        target = TARGET_COUNTS.get(pos, 0)

        if count < required:
            return 1.35
        if pos == "QB" and count >= 1:
            # One QB slot, 4-point passing TDs — a second QB is close to dead weight.
            return 0.45 if count == 1 else 0.15
        if pos == "TE" and count >= 1:
            return 0.55 if count == 1 else 0.2
        if count < target:
            return 1.10
        if count == target:
            return 0.85
        return 0.6


# Roughly how many of each position actually get drafted in this league.
# 10 teams, starters QB/WR/WR/RB/RB/TE/FLEX, 7 bench. Board rank alone badly
# misprices QB and TE here: only one starts, so demand runs out long before the
# board does. A QB ranked 156th overall is not "a late pick" — he is the 22nd QB
# in a league that drafts about 13, i.e. likely undrafted.
EXPECTED_DRAFTED_BY_POS = {
    "QB": 13,   # 10 starters + a few backups
    "TE": 14,   # 10 starters + a few streamers
    "RB": 46,   # 20 starters + flex + heavy bench
    "WR": 46,   # 20 starters + flex + heavy bench
}

# Players don't come off the board exactly at their rank. This is the slack used
# when deciding whether waiting is safe.
ADP_VARIANCE = 12


def is_out_for_season(player: dict) -> bool:
    return (player.get("injury") or {}).get("status") == "out_for_season"


def positional_rank(rankings: dict, player: dict) -> int:
    same = [p for p in rankings["players"] if p.get("pos") == player.get("pos")]
    same.sort(key=lambda p: p["rank"])
    for i, p in enumerate(same, start=1):
        if p["name"] == player["name"]:
            return i
    return len(same) + 1


def analyze_target(rankings: dict, state: DraftState, name: str) -> dict:
    """When, if ever, do you actually need to spend a pick on this player?

    Answers the real question behind "should I reach": what is the latest pick of
    mine at which this player is still plausibly available, and what does taking him
    earlier cost.
    """
    key = normalize_name(name)
    player = next(
        (p for p in rankings["players"] if normalize_name(p["name"]) == key), None
    )

    if player is None:
        return {
            "name": name,
            "on_board": False,
            "verdict": "not_ranked",
            "advice": (
                "Not on the ranked board. Kickers and defenses are excluded deliberately — "
                "with unlimited acquisitions and rolling waivers they are free to stream, "
                "so they belong in your last round or not at all."
            ),
        }

    if normalize_name(player["name"]) in state.drafted_keys:
        return {
            "name": player["name"], "on_board": True, "verdict": "gone",
            "advice": "Already drafted.",
        }

    pos = player.get("pos", "")
    pos_rank = positional_rank(rankings, player)
    expected_drafted = EXPECTED_DRAFTED_BY_POS.get(pos, 40)
    total_picks = state.teams * state.rounds
    my_picks = [p for _, p in picks_for_slot(state.slot, state.teams, state.rounds)] if state.slot else []
    remaining = [p for p in my_picks if p >= state.next_pick_number]

    result = {
        "name": player["name"], "on_board": True, "pos": pos,
        "board_rank": player["rank"], "positional_rank": pos_rank,
        "expected_drafted_at_pos": expected_drafted, "tier": player.get("tier"),
    }

    # Positional demand runs out before this player — nobody is competing for him.
    if pos_rank > expected_drafted:
        result.update(
            verdict="likely_undrafted",
            advice=(
                f"{pos}{pos_rank} in a league that drafts roughly {expected_drafted} {pos}s. "
                f"Very likely goes undrafted — you can take him with your final pick or add him "
                f"off waivers. Spending an earlier pick buys you nothing."
            ),
        )
        return result

    # Otherwise: latest of my picks that is still safely ahead of his expected slot.
    safe_by = player["rank"] - ADP_VARIANCE
    safe_picks = [p for p in remaining if p <= safe_by]

    if not remaining:
        result.update(verdict="no_picks_left", advice="You have no picks remaining.")
    elif safe_picks:
        latest = max(safe_picks)
        result["latest_safe_pick"] = latest
        result["safe_picks"] = safe_picks
        if latest == remaining[0]:
            result.update(
                verdict="last_chance",
                advice=(
                    f"Expected to go around #{player['rank']}. Your next pick (#{latest}) is the "
                    f"last one that comfortably beats that — after this you are gambling on him falling."
                ),
            )
        else:
            result.update(
                verdict="can_wait",
                advice=(
                    f"Expected to go around #{player['rank']}. You pick at "
                    f"{', '.join('#' + str(p) for p in safe_picks)} before then, so there is no need "
                    f"to take him at #{remaining[0]} — spend that on the best player available instead."
                ),
            )
    else:
        nxt = remaining[0]
        result.update(
            verdict="reach_now", next_pick=nxt,
            advice=(
                f"Expected to go around #{player['rank']}, which is ahead of your next pick (#{nxt}). "
                f"Getting him means reaching, and you would be paying above market to do it."
            ),
        )
    return result


def available_players(rankings: dict, state: DraftState) -> list[dict]:
    """Board players not yet drafted, in board order.

    Season-ending injuries are filtered here rather than merely rank-penalised —
    recommending a player who will not take a snap is worse than any ordering error.
    """
    taken = state.drafted_keys
    return [
        p
        for p in rankings["players"]
        if normalize_name(p["name"]) not in taken and not is_out_for_season(p)
    ]


def candidate_pool(
    rankings: dict,
    state: DraftState,
    pick_number: int,
    window: int = 30,
    assume_gone_above_pick: bool = False,
) -> list[dict]:
    """Players available at `pick_number`, scored by upside x need.

    Availability comes from what you have actually entered as drafted — not from an
    assumption that high-ranked players must be gone by now. That assumption is
    tempting (it hides obviously-stale names when you fall behind on entry) but the
    costs are lopsided: showing a player who is already gone costs one tap to
    dismiss, while hiding a player who genuinely fell costs you the best value on
    the board. Sliding elite players are the whole reason to watch a draft closely.

    `assume_gone_above_pick=True` restores the old filtering for anyone who would
    rather not see stale names, at that cost.

    The upper bound is a different thing and stays on: it bounds how deep to look
    for relevance at this pick, not who is still available.
    """
    available = available_players(rankings, state)
    pool = []
    for player in available:
        rank = player["rank"]
        if assume_gone_above_pick and rank < pick_number - 6:
            continue
        if rank > pick_number + window:
            continue

        upside = 200 - rank
        # A player falling well past their rank is a genuine value signal.
        fall_bonus = max(0, rank - pick_number) * 0.6
        multiplier = state.need_multiplier(player.get("pos", ""))
        pool.append(
            {
                **player,
                "score": (upside + fall_bonus) * multiplier,
                "need_multiplier": round(multiplier, 2),
                "falls_by": max(0, rank - pick_number),
                # Ranked well ahead of this pick and not marked drafted. Either a
                # genuine slide worth pouncing on, or a pick you never entered.
                "verify_available": rank < pick_number - 6,
            }
        )
    pool.sort(key=lambda p: p["score"], reverse=True)
    return pool


def positional_scarcity(
    rankings: dict,
    state: DraftState,
    pick_number: int,
    next_pick: int | None = None,
    valuation: dict | None = None,
) -> list[dict]:
    """Per position: what does waiting until your next pick actually cost, in POINTS?

    A need multiplier says what you lack; this says what disappears. The distinction
    decides picks: an unfilled TE slot is not urgent if the best TE still there next
    turn scores nearly the same.

    Ranks are the wrong currency for that comparison. A 13-rank slide at tight end and
    an 8-rank slide at receiver are not the same loss, because the positions have very
    different point curves — in this league RB falls about three times as steeply as TE
    per rank. When `valuation` is supplied, drop-off is measured in points off those
    curves; without it we fall back to rank distance, which is better than nothing but
    not comparable across positions.

    Players are assumed to leave the board roughly in board order. Imperfect — runs and
    reaches happen — but it is the same assumption the candidate pool already rests on.
    """
    avail = available_players(rankings, state)

    if next_pick is None:
        upcoming = state.my_upcoming_picks(limit=2)
        after = [p for _, p in upcoming if p > pick_number]
        next_pick = after[0] if after else None

    rows = []
    for pos in ("RB", "WR", "TE", "QB"):
        pool = sorted(
            (p for p in avail if p.get("pos") == pos and p["rank"] >= pick_number - 6),
            key=lambda p: p["rank"],
        )
        if not pool:
            continue

        def points_for(player: dict) -> float | None:
            if not valuation:
                return None
            v = valuation.get(normalize_name(player["name"]))
            return v.get("estimated_points") if v else None

        best_now = pool[0]
        row = {
            "pos": pos,
            "best_now": best_now["name"],
            "best_now_rank": best_now["rank"],
            "best_now_tier": best_now.get("tier"),
            "best_now_points": points_for(best_now),
            "starters_needed": state.unmet_starters().get(pos, 0),
            "units": "points" if valuation else "ranks",
        }

        if next_pick is None:
            # Draft over, or slot unset. Nothing to lose by waiting because there is
            # no waiting left — report zero rather than null so the UI shows a number.
            row.update(drop_off=0, drop_off_ranks=0, drop_off_points=0.0,
                       best_at_next_pick=None, note="No further picks.")
            rows.append(row)
            continue

        survivors = [p for p in pool if p["rank"] >= next_pick]
        gone_between = len([p for p in pool if p["rank"] < next_pick])

        if survivors:
            nxt = survivors[0]
            now_pts, next_pts = points_for(best_now), points_for(nxt)
            pts_drop = (
                round(now_pts - next_pts, 1)
                if now_pts is not None and next_pts is not None
                else None
            )
            rank_drop = nxt["rank"] - best_now["rank"]
            row.update(
                best_at_next_pick=nxt["name"],
                best_at_next_rank=nxt["rank"],
                best_at_next_tier=nxt.get("tier"),
                best_at_next_points=next_pts,
                drop_off_ranks=rank_drop,
                drop_off_points=pts_drop,
                # The headline number, in points where we have them.
                drop_off=pts_drop if pts_drop is not None else rank_drop,
                tier_drop=(nxt.get("tier") or 0) - (best_now.get("tier") or 0),
                likely_gone_between=gone_between,
            )
        else:
            row.update(
                best_at_next_pick=None,
                drop_off=999,
                drop_off_ranks=999,
                drop_off_points=None,
                tier_drop=99,
                likely_gone_between=gone_between,
                note="Nothing at this position is projected to last until your next pick.",
            )
        rows.append(row)

    rows.sort(key=lambda r: (-(r.get("drop_off") or 0), r["best_now_rank"]))
    return rows


def board_exhausted(rankings: dict, pick_number: int) -> bool:
    """True when the pick has run past the end of the ranked board."""
    max_rank = max(p["rank"] for p in rankings["players"])
    return pick_number > max_rank
