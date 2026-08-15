"""Generate the static draft plan — the no-dependency fallback.

Produces a single self-contained HTML file covering every draft slot, with ranked
candidates at each of your picks. No server, no network, no credentials. Open it on
the iPad and it works even if wifi dies mid-draft.

    python -m scripts.generate_plan                 # all slots, board only
    python -m scripts.generate_plan --slot 4        # one slot
    python -m scripts.generate_plan --enrich        # add Claude rationale (needs a key)

The core plan is computed from the board alone. --enrich is optional polish, so the
deliverable never depends on an API being reachable.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import ROOT, load_league_settings, load_rankings  # noqa: E402
from src.draft_state import (  # noqa: E402
    STARTER_REQUIREMENTS,
    TARGET_COUNTS,
    normalize_name,
    snake_pick_number,
)

CANDIDATES_PER_PICK = 12


def simulate_plan(rankings: dict, slot: int, teams: int, rounds: int) -> list[dict]:
    """Walk the draft for one slot, choosing greedily to project roster shape.

    The projection assumes players come off the board in board order and that you
    take the top recommendation each time. That is a simplification — it exists so
    later rounds can be need-weighted against a plausible roster, not because the
    draft will actually unfold this way. Each pick still lists many alternatives.
    """
    players = sorted(rankings["players"], key=lambda p: p["rank"])
    taken: set[str] = set()
    my_counts: dict[str, int] = {}
    plan = []

    for rnd in range(1, rounds + 1):
        pick_no = snake_pick_number(rnd, slot, teams)

        # Everyone ranked ahead of this pick is presumed gone.
        for p in players:
            if p["rank"] < pick_no:
                taken.add(normalize_name(p["name"]))

        pool = []
        for p in players:
            key = normalize_name(p["name"])
            if key in taken:
                continue
            if p["rank"] > pick_no + 40:
                continue
            pos = p.get("pos", "").upper()
            count = my_counts.get(pos, 0)
            required = STARTER_REQUIREMENTS.get(pos, 0)
            target = TARGET_COUNTS.get(pos, 0)

            if pos in {"K", "DEF", "DST"}:
                mult = 0.05
            elif count < required:
                mult = 1.35
            elif pos == "QB" and count >= 1:
                mult = 0.45 if count == 1 else 0.15
            elif pos == "TE" and count >= 1:
                mult = 0.55 if count == 1 else 0.2
            elif count < target:
                mult = 1.10
            elif count == target:
                mult = 0.85
            else:
                mult = 0.6

            score = (200 - p["rank"] + max(0, p["rank"] - pick_no) * 0.6) * mult
            pool.append({**p, "score": score, "mult": round(mult, 2)})

        pool.sort(key=lambda x: x["score"], reverse=True)
        candidates = pool[:CANDIDATES_PER_PICK]

        if candidates:
            pick = candidates[0]
            taken.add(normalize_name(pick["name"]))
            pos = pick.get("pos", "").upper()
            my_counts[pos] = my_counts.get(pos, 0) + 1

        unmet = {
            pos: req - my_counts.get(pos, 0)
            for pos, req in STARTER_REQUIREMENTS.items()
            if req - my_counts.get(pos, 0) > 0
        }

        plan.append(
            {
                "round": rnd,
                "pick": pick_no,
                "candidates": candidates,
                "projected_counts": dict(my_counts),
                "unmet_starters": unmet,
                "exhausted": not candidates,
            }
        )

    return plan


def render_html(rankings: dict, league: dict, plans: dict[int, list[dict]], teams: int) -> str:
    meta = rankings["meta"]
    strategy = meta.get("league_specific_strategy", {})
    max_rank = max(p["rank"] for p in rankings["players"])

    def esc(s) -> str:
        return html.escape(str(s))

    slot_sections = []
    for slot, plan in sorted(plans.items()):
        rows = []
        for entry in plan:
            if entry["exhausted"]:
                rows.append(
                    f"""<div class="rd exhausted">
                        <div class="rd-head"><span class="rn">R{entry['round']}</span>
                        <span class="pn">pick {entry['pick']}</span></div>
                        <div class="warn">Past the end of the {max_rank}-player board.
                        No ranked data — autodraft from here, or extend the board.</div>
                    </div>"""
                )
                continue

            unmet = entry["unmet_starters"]
            need = (
                " · ".join(f"need {v} {k}" for k, v in unmet.items())
                if unmet
                else "all starters covered"
            )
            counts = " ".join(f"{k}{v}" for k, v in sorted(entry["projected_counts"].items()))

            cands = "".join(
                f"""<li class="{'top' if i == 0 else ''}">
                    <span class="nm">{esc(c['name'])}</span>
                    <span class="ps {esc(c['pos'])}">{esc(c['pos'])}</span>
                    <span class="tm">{esc(c['team'])}</span>
                    <span class="tr">T{esc(c['tier'])}</span>
                    <span class="rk">#{esc(c['rank'])}</span>
                </li>"""
                for i, c in enumerate(entry["candidates"])
            )

            rows.append(
                f"""<div class="rd">
                    <div class="rd-head">
                        <span class="rn">R{entry['round']}</span>
                        <span class="pn">pick {entry['pick']}</span>
                        <span class="need">{esc(need)}</span>
                        <span class="proj">{esc(counts)}</span>
                    </div>
                    <ol class="cands">{cands}</ol>
                </div>"""
            )

        slot_sections.append(
            f'<section class="slot" id="slot{slot}" hidden><h2>Draft slot {slot}</h2>{"".join(rows)}</section>'
        )

    buttons = "".join(
        f'<button data-slot="{s}" class="slotbtn">{s}</button>' for s in sorted(plans)
    )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Draft Plan — {esc(league['league_identity']['league_name'])}</title>
<style>
:root {{ --bg:#0f1115; --panel:#171a21; --line:#2a2f3a; --text:#e8eaed; --dim:#9aa1ae;
        --accent:#4ea1ff; --good:#46c88a; --warn:#f5a623; }}
* {{ box-sizing:border-box }}
body {{ margin:0; background:var(--bg); color:var(--text); font:16px/1.5 -apple-system,BlinkMacSystemFont,system-ui,sans-serif; }}
header {{ padding:16px; border-bottom:1px solid var(--line); position:sticky; top:0; background:rgba(15,17,21,.96); backdrop-filter:blur(10px); z-index:5 }}
h1 {{ margin:0 0 4px; font-size:19px }}
.sub {{ color:var(--dim); font-size:14px }}
.slotbar {{ display:flex; gap:6px; flex-wrap:wrap; margin-top:12px }}
.slotbtn {{ flex:1; min-width:44px; padding:11px 0; border-radius:9px; border:1px solid var(--line);
           background:var(--panel); color:var(--text); font:inherit; font-weight:600; cursor:pointer }}
.slotbtn.on {{ background:var(--accent); color:#04182e; border-color:transparent }}
main {{ padding:16px; max-width:1000px; margin:0 auto }}
.strategy {{ background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:14px 16px; margin-bottom:16px; font-size:14.5px; color:var(--dim) }}
.strategy b {{ color:var(--text) }}
.rd {{ background:var(--panel); border:1px solid var(--line); border-radius:12px; margin-bottom:12px; overflow:hidden }}
.rd-head {{ display:flex; align-items:baseline; gap:10px; padding:10px 14px; border-bottom:1px solid var(--line); flex-wrap:wrap }}
.rn {{ font-weight:700; font-size:17px }}
.pn {{ color:var(--dim); font-size:14px }}
.need {{ margin-left:auto; color:var(--warn); font-size:13px }}
.proj {{ color:var(--dim); font-size:12px; font-variant-numeric:tabular-nums }}
ol.cands {{ list-style:none; margin:0; padding:0; counter-reset:c }}
ol.cands li {{ counter-increment:c; display:flex; align-items:baseline; gap:9px; padding:8px 14px; border-bottom:1px solid rgba(42,47,58,.5) }}
ol.cands li:last-child {{ border-bottom:0 }}
ol.cands li::before {{ content:counter(c); width:20px; color:var(--dim); font-size:12px; font-variant-numeric:tabular-nums }}
ol.cands li.top {{ background:rgba(78,161,255,.07) }}
ol.cands li.top .nm {{ color:var(--accent) }}
.nm {{ font-weight:600; flex:1 }}
.ps {{ font-size:11px; font-weight:700; padding:2px 7px; border-radius:5px; background:#232833; color:var(--dim) }}
.ps.RB {{ background:#1d3a2a; color:#6ee7a8 }} .ps.WR {{ background:#1b3350; color:#74b6ff }}
.ps.TE {{ background:#3d2f14; color:#f0c46b }} .ps.QB {{ background:#3a1f30; color:#ff9ec4 }}
.tm,.tr,.rk {{ font-size:12px; color:var(--dim); font-variant-numeric:tabular-nums }}
.warn {{ padding:14px; color:var(--warn); font-size:14px }}
.exhausted {{ opacity:.75 }}
@media print {{ body {{ background:#fff; color:#000 }} .slotbar,header {{ position:static }} .slot {{ display:block !important }} }}
</style></head><body>
<header>
  <h1>Draft Plan — {esc(league['league_identity']['league_name'])}</h1>
  <div class="sub">{esc(meta['format_basis'])} · {teams} teams · snake ·
       board {max_rank} deep</div>
  <div class="slotbar">{buttons}</div>
</header>
<main>
  <div class="strategy">
    <b>Standard scoring — receptions are worth zero.</b> Public rankings are almost all PPR,
    so slot receivers and pass-catching backs are overvalued there and volume rushers are
    undervalued. This board is already converted.<br><br>
    <b>8 of 10 teams make the playoffs.</b> {esc(strategy.get('draft_for_ceiling',''))}<br><br>
    <b>Don't draft K or DEF.</b> {esc(strategy.get('stream_k_and_def',''))}<br><br>
    Pick your slot above once the order is drawn. At each pick, take the highest name still
    on the board — cross off anyone already gone. Tier (T) matters more than exact rank;
    players inside a tier are close to interchangeable.
  </div>
  {''.join(slot_sections)}
</main>
<script>
const btns = document.querySelectorAll('.slotbtn');
function show(slot) {{
  document.querySelectorAll('.slot').forEach(s => s.hidden = (s.id !== 'slot' + slot));
  btns.forEach(b => b.classList.toggle('on', b.dataset.slot === String(slot)));
  localStorage.setItem('draftSlot', slot);
}}
btns.forEach(b => b.onclick = () => show(b.dataset.slot));
show(localStorage.getItem('draftSlot') || btns[0].dataset.slot);
</script>
</body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the static draft plan")
    parser.add_argument("--slot", type=int, help="only this slot (default: all)")
    parser.add_argument("--teams", type=int, default=10)
    parser.add_argument("--rounds", type=int, default=16)
    parser.add_argument("--out", default="draft_plan.html")
    args = parser.parse_args()

    rankings = load_rankings()
    league = load_league_settings()

    slots = [args.slot] if args.slot else list(range(1, args.teams + 1))
    plans = {s: simulate_plan(rankings, s, args.teams, args.rounds) for s in slots}

    out_path = ROOT / args.out
    out_path.write_text(render_html(rankings, league, plans, args.teams), encoding="utf-8")

    max_rank = max(p["rank"] for p in rankings["players"])
    covered = sum(1 for e in plans[slots[0]] if not e["exhausted"])
    print(f"Wrote {out_path}")
    print(f"  slots: {len(slots)}  rounds: {args.rounds}")
    print(f"  board depth: {max_rank} — covers {covered} of {args.rounds} rounds")
    if covered < args.rounds:
        print(f"  NOTE: rounds {covered + 1}-{args.rounds} have no ranked data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
