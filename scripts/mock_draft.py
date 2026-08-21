"""Hybrid mock draft: you drive some teams, the rest fill themselves.

    python -m scripts.mock_draft --reset --me 4 --control 3,5 --rounds 3
    python -m scripts.mock_draft --me 4 --control 3,5 --advance

Auto-fills every slot you are not driving, then stops the moment a slot you control
is on the clock and reports the board. You enter that pick — your own through the app,
the controlled teams however you like — and run --advance again.

The point is adversarial input. The plain simulator always takes one of the top few
available, so it can never produce a reach, a positional run, or a genuinely strange
pick. Those are exactly the board states the recommender has never been tested against.

Note the app does not model opponents: it tracks who is gone and what you own, nothing
else. Controlling teams 3 and 5 changes *what gets picked*, which is the variable that
matters — not *who picks it*, which nothing downstream reads.
"""

from __future__ import annotations

import argparse
import random
import sys
import urllib.parse
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE = "http://127.0.0.1:8000"


def slot_for_pick(pick: int, teams: int) -> int:
    """Which draft slot owns this overall pick, snake order."""
    rnd = (pick - 1) // teams + 1
    idx = (pick - 1) % teams
    return idx + 1 if rnd % 2 == 1 else teams - idx


def status() -> dict:
    return httpx.get(f"{BASE}/api/status", timeout=30).json()


def board() -> list[dict]:
    return httpx.get(f"{BASE}/api/board", timeout=30).json()


def take(name: str, mine: bool) -> dict:
    return httpx.post(
        f"{BASE}/api/manual-pick/{urllib.parse.quote(name)}",
        params={"mine": str(mine).lower()},
        timeout=30,
    ).json()


def auto_pick() -> str | None:
    avail = sorted((p for p in board() if not p["drafted"]), key=lambda p: p["rank"])
    if not avail:
        return None
    top = avail[: min(6, len(avail))]
    return random.choices(top, weights=[40, 24, 14, 9, 8, 5][: len(top)], k=1)[0]["name"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--me", type=int, required=True, help="your draft slot")
    ap.add_argument("--control", default="", help="comma-separated slots you also drive")
    ap.add_argument("--teams", type=int, default=10)
    ap.add_argument("--rounds", type=int, default=16)
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--advance", action="store_true", help="run until a driven slot is up")
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    controlled = {int(x) for x in args.control.split(",") if x.strip()}
    driven = controlled | {args.me}
    last_pick = args.teams * args.rounds

    if args.reset:
        httpx.post(f"{BASE}/api/reset", params={"keep_slot": "false"}, timeout=30)
        httpx.post(f"{BASE}/api/slot/{args.me}", timeout=30)
        print(f"reset — you are slot {args.me}, driving {sorted(driven)}")

    filled = []
    while True:
        s = status()
        pick = s["draft"]["next_pick"]
        if pick > last_pick:
            print(f"\nreached the end of round {args.rounds}.")
            break
        slot = slot_for_pick(pick, args.teams)
        if slot in driven:
            break
        if not args.advance and not args.reset:
            break
        name = auto_pick()
        if name is None:
            print("board exhausted")
            break
        take(name, mine=False)
        filled.append((pick, slot, name))

    if filled:
        print("\nauto-picked while advancing:")
        for pk, sl, nm in filled:
            print(f"  {pk:>3}. (team {sl}) {nm}")

    s = status()
    pick = s["draft"]["next_pick"]
    if pick <= last_pick:
        slot = slot_for_pick(pick, args.teams)
        rnd = (pick - 1) // args.teams + 1
        who = "YOU" if slot == args.me else f"TEAM {slot} (you control)"
        print(f"\n>>> pick {pick}, round {rnd} — on the clock: {who}")
        nxt = [
            (p, slot_for_pick(p, args.teams))
            for p in range(pick + 1, min(pick + 6, last_pick + 1))
        ]
        print("    coming up: " + ", ".join(f"{p}=slot{sl}" for p, sl in nxt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
