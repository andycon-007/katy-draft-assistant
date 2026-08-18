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

    # ------------------------------------------------------------- derived

    @property
    def picks_made(self) -> int:
        return len(self.drafted)

    @property
    def next_pick_number(self) -> int:
        return self.picks_made + 1

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


def is_out_for_season(player: dict) -> bool:
    return (player.get("injury") or {}).get("status") == "out_for_season"


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
    rankings: dict, state: DraftState, pick_number: int, window: int = 30
) -> list[dict]:
    """Players plausibly available at `pick_number`, scored by upside x need.

    Board rank approximates consensus draft order, so anyone ranked far ahead of
    this pick is likely gone. The window admits players who fall, which is where
    most of the value in a draft actually comes from.
    """
    available = available_players(rankings, state)
    pool = []
    for player in available:
        rank = player["rank"]
        # Allow a small reach above the pick, and a wide window below it.
        if rank < pick_number - 6:
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
            }
        )
    pool.sort(key=lambda p: p["score"], reverse=True)
    return pool


def board_exhausted(rankings: dict, pick_number: int) -> bool:
    """True when the pick has run past the end of the ranked board."""
    max_rank = max(p["rank"] for p in rankings["players"])
    return pick_number > max_rank
