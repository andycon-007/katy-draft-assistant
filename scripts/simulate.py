"""Drive a dry-run draft: simulate the other teams, stop when it's your turn.

    python -m scripts.simulate --to 17     advance until pick 17 is on the clock
    python -m scripts.simulate --reset     clear state first

Other managers pick from the top of the remaining board with some noise, so runs and
mild reaches happen the way they do in a real room. They are not trying to be smart —
the point is a moving board to react to, not a realistic opponent model.
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


def status() -> dict:
    return httpx.get(f"{BASE}/api/status", timeout=30).json()


def board() -> list[dict]:
    return httpx.get(f"{BASE}/api/board", timeout=30).json()


def pick_for_other_team() -> str | None:
    """Choose a plausible pick for whoever is on the clock."""
    avail = [p for p in board() if not p["drafted"]]
    if not avail:
        return None
    avail.sort(key=lambda p: p["rank"])
    # Mostly the best available, sometimes a small reach — enough to create runs.
    top = avail[: min(6, len(avail))]
    weights = [40, 24, 14, 9, 8, 5][: len(top)]
    return random.choices(top, weights=weights, k=1)[0]["name"]


def mark(name: str, mine: bool = False) -> dict:
    return httpx.post(
        f"{BASE}/api/manual-pick/{urllib.parse.quote(name)}",
        params={"mine": str(mine).lower()},
        timeout=30,
    ).json()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", type=int, help="advance until this overall pick is on the clock")
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--slot", type=int)
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    if args.reset:
        httpx.post(f"{BASE}/api/reset", timeout=30)
        print("state cleared")
    if args.slot:
        httpx.post(f"{BASE}/api/slot/{args.slot}", timeout=30)
        print(f"slot set to {args.slot}")

    s = status()
    target = args.to or s["draft"]["next_pick"]
    made = []

    while True:
        s = status()
        cur = s["draft"]["next_pick"]
        if cur >= target:
            break
        name = pick_for_other_team()
        if name is None:
            print("board exhausted")
            break
        r = mark(name, mine=False)
        made.append((cur, r.get("marked", name)))

    if made:
        print(f"\nsimulated picks {made[0][0]}-{made[-1][0]}:")
        for pk, nm in made:
            print(f"  {pk:3}. {nm}")

    s = status()
    d = s["draft"]
    print(f"\nnow on pick {d['next_pick']} (round {d['current_round']}) — your turn: {d['is_my_turn']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
