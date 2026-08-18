"""Compute 2025 standard-scoring points and Value Over Replacement.

    python -m scripts.compute_vor

VOR answers the question board rank cannot: how many more points does this player
score than the player you would otherwise have started at that position? It is the
only way to compare across positions, because a 13-rank gap at TE and an 8-rank gap
at WR are not the same number of points.

Replacement level is the last starter you would realistically roster at each position
in THIS league — 10 teams, starting QB/WR/WR/RB/RB/TE/FLEX. So roughly the 10th QB,
10th TE, and (allowing for the flex and bye-week churn) about the 25th RB and WR.

These are 2025 actuals, not 2026 projections. Read the caveats in the output.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import DATA_DIR, load_league_settings  # noqa: E402

# Where the last startable player at each position sits in a 10-team league.
REPLACEMENT_RANK = {"QB": 10, "RB": 25, "WR": 25, "TE": 10}


def main() -> int:
    stats = json.loads((DATA_DIR / "sources" / "stats_2025.json").read_text())
    league = load_league_settings()
    sc = league["scoring"]

    rec_pt = 1.0 / sc["receiving"]["yards_per_point"]
    rush_pt = 1.0 / sc["rushing"]["yards_per_point"]
    rec_td = sc["receiving"]["touchdown"]
    rush_td = sc["rushing"]["touchdown"]
    per_rec = sc["receiving"]["reception"]

    players: dict[str, dict] = {}

    def ensure(name, pos, team):
        if name not in players:
            players[name] = {"name": name, "pos": pos, "team": team, "pts": 0.0, "line": {}}
        return players[name]

    for name, pos, team, rec, yds, td in stats["receiving"]:
        p = ensure(name, pos, team)
        p["pts"] += yds * rec_pt + td * rec_td + rec * per_rec
        p["line"].update(rec=rec, rec_yds=yds, rec_td=td)

    for name, pos, team, att, yds, td in stats["rushing"]:
        p = ensure(name, pos, team)
        p["pts"] += yds * rush_pt + td * rush_td
        p["line"].update(rush_yds=yds, rush_td=td)

    for name, rec, yds, td in stats["rb_receiving"]:
        p = ensure(name, "RB", "?")
        p["pts"] += yds * rec_pt + td * rec_td + rec * per_rec
        p["line"].update(rec=rec, rec_yds=yds, rec_td=td)

    by_pos: dict[str, list[dict]] = {}
    for p in players.values():
        by_pos.setdefault(p["pos"], []).append(p)
    for pos in by_pos:
        by_pos[pos].sort(key=lambda x: -x["pts"])

    print(f"2025 ACTUALS — standard scoring ({per_rec} pts per reception)")
    print("=" * 74)

    replacement = {}
    for pos, rank in REPLACEMENT_RANK.items():
        pool = by_pos.get(pos, [])
        if len(pool) >= rank:
            replacement[pos] = pool[rank - 1]["pts"]
        elif pool:
            replacement[pos] = pool[-1]["pts"]
            print(f"  ! only {len(pool)} {pos}s in the data; replacement is approximate")

    for pos in ("TE", "WR", "RB"):
        pool = by_pos.get(pos, [])
        if not pool:
            continue
        repl = replacement.get(pos, 0)
        print()
        print(f"{pos}  (replacement = {pos}{REPLACEMENT_RANK[pos]} at {repl:.1f} pts)")
        print(f"  {'#':<3} {'player':<22} {'pts':>7} {'VOR':>8}   line")
        for i, p in enumerate(pool[:14], 1):
            L = p["line"]
            bits = []
            if L.get("rush_yds"):
                bits.append(f"{L['rush_yds']} ru / {L.get('rush_td',0)} TD")
            if L.get("rec_yds"):
                bits.append(f"{L.get('rec',0)}-{L['rec_yds']} rec / {L.get('rec_td',0)} TD")
            print(f"  {i:<3} {p['name']:<22} {p['pts']:>7.1f} {p['pts']-repl:>+8.1f}   {'; '.join(bits)}")

    print()
    print("=" * 74)
    print("CROSS-POSITION COMPARISON — the actual question")
    print("=" * 74)
    watch = ["Brock Bowers", "Trey McBride", "A.J. Brown", "Drake London",
             "De'Von Achane", "Omarion Hampton", "Kyren Williams", "Chase Brown"]
    rows = []
    for nm in watch:
        p = players.get(nm)
        if not p:
            rows.append((nm, None, None))
            continue
        rows.append((nm, p, p["pts"] - replacement.get(p["pos"], 0)))
    rows.sort(key=lambda r: (r[2] is None, -(r[2] or 0)))
    for nm, p, vor in rows:
        if p is None:
            print(f"  {nm:<22} no 2025 data (rookie or not in the fetched tables)")
        else:
            print(f"  {nm:<22} {p['pos']:<3} {p['pts']:>6.1f} pts   VOR {vor:>+6.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
