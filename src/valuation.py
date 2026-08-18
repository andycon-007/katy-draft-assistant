"""Points-based valuation: 2025 actuals where they exist, curve estimates where they don't.

Two numbers per player, deliberately kept apart:

  measured   — 2025 actual points in this league's scoring. Real, backward-looking,
               and absent for every rookie and anyone the source tables didn't cover.
  estimated  — points implied by the player's 2026 consensus board rank, read off a
               curve fitted to players who do have 2025 data. Available for everyone.

Neither alone is trustworthy. Measured says what happened; estimated says what the
market expects. Blending them into one score would hide the most useful signal in the
pair, which is where they disagree: a player whose rank implies far more than he
produced is a market bet on a bounce-back, and one whose production far exceeded his
rank is either a breakout the market hasn't priced or a fluke it has already
discounted. Both are worth seeing.

Known limitation: the curve is fitted to realized finishes, while board rank is a
preseason expectation. Realized outcomes spread wider than expectations, so estimates
are reasonable central values but understate the tails — most of all for rookies,
who both bust and break out more often than the curve implies.
"""

from __future__ import annotations

import json
from pathlib import Path

from .config import DATA_DIR
from .draft_state import normalize_name

# Last startable player at each position in a 10-team league starting
# QB/WR/WR/RB/RB/TE/FLEX. The flex and bye churn push RB/WR deeper than the
# nominal two starters.
REPLACEMENT_RANK = {"QB": 10, "RB": 25, "WR": 25, "TE": 10}


def _load_stats() -> dict:
    path = DATA_DIR / "sources" / "stats_2025.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def measured_points(league: dict) -> dict[str, dict]:
    """2025 actual points per player, in this league's scoring."""
    stats = _load_stats()
    if not stats:
        return {}

    sc = league["scoring"]
    rec_per_yd = 1.0 / sc["receiving"]["yards_per_point"]
    rush_per_yd = 1.0 / sc["rushing"]["yards_per_point"]
    rec_td, rush_td = sc["receiving"]["touchdown"], sc["rushing"]["touchdown"]
    per_rec = sc["receiving"]["reception"]

    out: dict[str, dict] = {}

    def ensure(name, pos):
        key = normalize_name(name)
        if key not in out:
            out[key] = {"name": name, "pos": pos, "points": 0.0, "saw_rush": False, "saw_rec": False}
        return out[key]

    for name, pos, _team, rec, yds, td in stats.get("receiving", []):
        p = ensure(name, pos)
        p["points"] += yds * rec_per_yd + td * rec_td + rec * per_rec
        p["saw_rec"] = True

    for name, pos, _team, _att, yds, td in stats.get("rushing", []):
        p = ensure(name, pos)
        p["points"] += yds * rush_per_yd + td * rush_td
        p["saw_rush"] = True

    for name, rec, yds, td in stats.get("rb_receiving", []):
        p = ensure(name, "RB")
        p["points"] += yds * rec_per_yd + td * rec_td + rec * per_rec
        p["saw_rec"] = True

    # The source tables are top-N per category, so a back who missed the rushing
    # table has a receiving-only total that looks like a collapse rather than a gap
    # in coverage. Scoring that as real is worse than having no data: it invents
    # underperformers. Only trust a running back's total if his rushing was observed.
    for p in out.values():
        p["complete"] = p["saw_rush"] if p["pos"] == "RB" else p["saw_rec"]

    return {k: p for k, p in out.items() if p["complete"]}


SMOOTH_WINDOW = 5


def _fit_curves(rankings: dict, measured: dict) -> dict[str, list[tuple[int, float]]]:
    """Per position: a smoothed curve of expected points by positional board rank.

    Indexed by 2026 board position, not 2025 finish — the curve has to be keyed on
    the thing we look players up with.

    Smoothing is the point, not a nicety. A curve threaded exactly through each
    observed player returns that player's own season when you query his rank, which
    makes the estimate a tautology and the measured-vs-estimated gap identically
    zero. A rolling mean over neighbouring ranks gives what we actually want: what a
    typical player at this rank scored. Then enforce non-increasing, since a later
    board rank should never imply more points.
    """
    curves: dict[str, list[tuple[int, float]]] = {}
    for pos in ("QB", "RB", "WR", "TE"):
        board_pos = sorted(
            (p for p in rankings["players"] if p.get("pos") == pos),
            key=lambda p: p["rank"],
        )
        observed = []
        for i, p in enumerate(board_pos, start=1):
            m = measured.get(normalize_name(p["name"]))
            if m:
                observed.append((i, m["points"]))

        if len(observed) < 3:
            curves[pos] = observed
            continue

        smoothed = []
        for idx, (rank, _) in enumerate(observed):
            lo = max(0, idx - SMOOTH_WINDOW // 2)
            hi = min(len(observed), lo + SMOOTH_WINDOW)
            lo = max(0, hi - SMOOTH_WINDOW)
            window = [pts for _, pts in observed[lo:hi]]
            smoothed.append((rank, sum(window) / len(window)))

        # Enforce monotonic non-increasing.
        for i in range(1, len(smoothed)):
            if smoothed[i][1] > smoothed[i - 1][1]:
                smoothed[i] = (smoothed[i][0], smoothed[i - 1][1])

        curves[pos] = smoothed
    return curves


def _interpolate(curve: list[tuple[int, float]], pos_rank: int) -> float | None:
    """Read points off the curve at a positional rank, interpolating between points."""
    if not curve:
        return None
    if pos_rank <= curve[0][0]:
        return curve[0][1]
    if pos_rank >= curve[-1][0]:
        # Past observed depth: decay gently rather than pretending the curve is flat.
        last_rank, last_pts = curve[-1]
        return max(0.0, last_pts * (0.97 ** (pos_rank - last_rank)))
    for (r1, p1), (r2, p2) in zip(curve, curve[1:]):
        if r1 <= pos_rank <= r2:
            if r2 == r1:
                return p1
            t = (pos_rank - r1) / (r2 - r1)
            return p1 + t * (p2 - p1)
    return curve[-1][1]


def build_valuation(rankings: dict, league: dict) -> dict[str, dict]:
    """Per player: measured points, estimated points, VOR for each, and a confidence."""
    measured = measured_points(league)
    curves = _fit_curves(rankings, measured)

    # Replacement level, computed on estimates so every position has one even where
    # measured coverage is thin.
    replacement: dict[str, float] = {}
    for pos, rank in REPLACEMENT_RANK.items():
        val = _interpolate(curves.get(pos, []), rank)
        replacement[pos] = val if val is not None else 0.0

    pos_counter: dict[str, int] = {}
    out: dict[str, dict] = {}
    for p in sorted(rankings["players"], key=lambda x: x["rank"]):
        pos = p.get("pos", "")
        pos_counter[pos] = pos_counter.get(pos, 0) + 1
        pos_rank = pos_counter[pos]

        est = _interpolate(curves.get(pos, []), pos_rank)
        m = measured.get(normalize_name(p["name"]))
        repl = replacement.get(pos)

        entry = {
            "name": p["name"],
            "pos": pos,
            "positional_rank": pos_rank,
            "replacement": round(repl, 1) if repl is not None else None,
            "estimated_points": round(est, 1) if est is not None else None,
            "estimated_vor": round(est - repl, 1) if est is not None and repl is not None else None,
            "measured_points": round(m["points"], 1) if m else None,
            "measured_vor": round(m["points"] - repl, 1) if m and repl is not None else None,
            "has_2025_data": m is not None,
        }

        # Where the two disagree sharply, that gap is the interesting part.
        if entry["measured_vor"] is not None and entry["estimated_vor"] is not None:
            entry["gap"] = round(entry["measured_vor"] - entry["estimated_vor"], 1)
            entry["confidence"] = "measured"
        else:
            entry["gap"] = None
            # No 2025 data at all: rookie, or missed the season, or the source tables
            # didn't go deep enough. The estimate is all we have.
            entry["confidence"] = "estimated_only"

        out[normalize_name(p["name"])] = entry

    return out
