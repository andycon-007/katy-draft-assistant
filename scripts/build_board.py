"""Rebuild data/rankings.json by blending sources and applying injury status.

    python -m scripts.build_board

Inputs:
  data/sources/br_standard_top100.json   the existing standard-converted board
  data/sources/rotoworld_top200.json     NBC/Rotoworld top 200, published 2026-08-15
  data/sources/injuries_2026_08_15.json  camp injury status

Method, and its limits:

  Consensus rank is the mean of whichever source ranks a player. Two sources is thin
  — it is enough to cancel single-outlet idiosyncrasy (Bleacher Report had
  Smith-Njigba 3 spots higher than anyone else) but not enough to call the result a
  true consensus.

  Standard-scoring adjustments carry over from the existing board, which was already
  converted from PPR. Players appearing only in the Rotoworld list keep their
  published order; that list is PPR-leaning, so ranks past ~100 are less
  standard-correct than the top of the board. They are bench and dart-throw territory
  where tier matters more than exact position, so this is an acceptable trade rather
  than a hidden flaw.

  Injury penalties are additive rank shifts from a fixed scale, not projections. They
  encode "this is riskier than the published rank implies," nothing more.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import DATA_DIR  # noqa: E402
from src.draft_state import normalize_name  # noqa: E402

SOURCES = DATA_DIR / "sources"

# Tier boundaries by blended rank. Wider bands deeper in the board, because rank
# precision degrades faster than tier membership does.
TIER_BREAKS = [5, 10, 18, 26, 32, 38, 45, 53, 60, 68, 75, 82, 90, 100,
               115, 130, 145, 160, 175, 200]


def tier_for(rank: int) -> int:
    for i, cutoff in enumerate(TIER_BREAKS, start=1):
        if rank <= cutoff:
            return i
    return len(TIER_BREAKS) + 1


def load(name: str) -> dict:
    return json.loads((SOURCES / name).read_text(encoding="utf-8"))


def main() -> int:
    br = load("br_standard_top100.json")
    roto = load("rotoworld_top200.json")
    inj = load("injuries_2026_08_15.json")

    penalties = inj["penalty_scale"]
    injuries = {normalize_name(k): {**v, "name": k} for k, v in inj["players"].items()}

    merged: dict[str, dict] = {}

    for p in br["players"]:
        key = normalize_name(p["name"])
        merged[key] = {
            "name": p["name"],
            "pos": p["pos"],
            "team": p["team"],
            "bye": p.get("bye"),
            "ranks": {"br_standard": p["rank"]},
            "note": p.get("note"),
            "ppr_rank": p.get("ppr_rank"),
        }

    seen_roto: set[str] = set()
    for rank, name, pos, team in roto["players"]:
        key = normalize_name(name)
        if key in seen_roto:
            continue  # source list contains a duplicate entry
        seen_roto.add(key)
        if key in merged:
            merged[key]["ranks"]["rotoworld"] = rank
        else:
            merged[key] = {
                "name": name,
                "pos": pos,
                "team": team,
                "bye": None,
                "ranks": {"rotoworld": rank},
                "note": None,
                "ppr_rank": None,
            }

    rows, excluded = [], []
    for key, p in merged.items():
        ranks = list(p["ranks"].values())
        blended = sum(ranks) / len(ranks)

        injury = injuries.get(key)
        if injury:
            status = injury["status"]
            if status == "out_for_season":
                excluded.append(f"{p['name']} ({injury['issue']})")
                continue
            blended += penalties.get(status, 0)
            p["injury"] = {
                "issue": injury["issue"],
                "status": status,
                "penalty": penalties.get(status, 0),
                "detail": injury.get("detail"),
            }

        p["blended"] = blended
        p["sources"] = list(p["ranks"].keys())
        rows.append(p)

    # Kickers and defenses are freely streamable under unlimited waivers.
    rows = [r for r in rows if r["pos"] not in {"K", "DEF", "DST"}]
    rows.sort(key=lambda r: r["blended"])

    players = []
    for i, r in enumerate(rows, start=1):
        entry = {
            "rank": i,
            "name": r["name"],
            "pos": r["pos"],
            "team": r["team"],
            "bye": r["bye"],
            "tier": tier_for(i),
            "sources": r["sources"],
            "source_ranks": r["ranks"],
        }
        if r.get("ppr_rank"):
            entry["ppr_rank"] = r["ppr_rank"]
        if r.get("note"):
            entry["note"] = r["note"]
        if r.get("injury"):
            entry["injury"] = r["injury"]
        players.append(entry)

    existing = json.loads((DATA_DIR / "rankings.json").read_text(encoding="utf-8"))
    meta = existing["meta"]
    meta["revised_on"] = "2026-08-15"
    meta["coverage"] = f"{len(players)} players — covers all 16 rounds of a 10-team draft"
    meta["build"] = {
        "method": "Blended consensus: mean of available source ranks, then additive injury penalties.",
        "sources": {
            "br_standard": "Bleacher Report top 100 PPR, converted to standard scoring",
            "rotoworld": f"{roto['source']} (published {roto['retrieved']})",
            "injuries": f"Camp injury status as of {inj['retrieved']}",
        },
        "excluded_out_for_season": excluded,
        "caveats": [
            "Two sources is enough to cancel single-outlet outliers, not enough to be a true consensus.",
            "Players ranked past ~100 come from the Rotoworld list only, which is PPR-leaning — their standard-scoring correction is weaker than the top of the board.",
            "Injury penalties are fixed rank shifts encoding added risk, not projections.",
            "Kickers and defenses are deliberately excluded; unlimited waivers make them streamable.",
        ],
    }

    out = {
        "meta": meta,
        "bye_weeks": existing["bye_weeks"],
        "tiers": {str(i): f"Tier {i}" for i in range(1, len(TIER_BREAKS) + 2)},
        "players": players,
    }
    (DATA_DIR / "rankings.json").write_text(json.dumps(out, indent=2), encoding="utf-8")

    injured = [p for p in players if p.get("injury")]
    print(f"Wrote {DATA_DIR / 'rankings.json'}")
    print(f"  players: {len(players)}  (was {len(existing['players'])})")
    print(f"  both sources: {sum(1 for p in players if len(p['sources']) == 2)}")
    print(f"  rotoworld only: {sum(1 for p in players if p['sources'] == ['rotoworld'])}")
    print(f"  carrying injury flags: {len(injured)}")
    print(f"  excluded (out for season): {excluded or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
