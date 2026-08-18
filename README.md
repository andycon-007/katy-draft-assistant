# Fantasy Draft Assistant

Live pick recommender for **Tigers of Katy Baseball** (Yahoo #878541), 2026 season.
Runs on the Mac mini, viewed from the iPad over Tailscale.

## What it does

Polls Yahoo's draft-results feed during the live draft, tracks who's gone and what
your roster needs, and asks Claude Opus 5 for ten ranked candidates at each of your
picks — sorted by ceiling, tilted for roster need.

## The two things that make this league unusual

Both are baked into the recommendation prompt, and both cut against public rankings:

1. **Standard scoring — zero points per reception.** Nearly every ranking you'll find
   online is PPR. Slot receivers and pass-catching backs are systematically overvalued
   by those lists; volume rushers and touchdown-dependent players are undervalued.
   The board in `data/rankings.json` has already been converted.

2. **8 of 10 teams make the playoffs.** Qualifying is close to automatic, so a safe
   floor is nearly worthless. In 2025 the champion ranked **7th of 10** in points
   scored, a 6-8 team finished runner-up, and the 11-3 scoring leader finished 3rd.
   The engine drafts for ceiling accordingly.

## Setup

### 1. Install

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 2. Register a Yahoo app

At **developer.yahoo.com/apps/create**, signed in with the Yahoo account that is in
the league:

| Field | Value |
|---|---|
| Application Name | anything, e.g. `Katy Draft Assistant` |
| Redirect URI | `https://localhost:8000/callback` — must be **https** |
| API Permissions | **Fantasy Sports → Read** |

Read-only is deliberate. The app observes the draft and never needs to make a pick,
so there's no reason for it to hold write access to your team.

### 3. Configure

```bash
cp .env.example .env
```

Fill in `YAHOO_CLIENT_ID`, `YAHOO_CLIENT_SECRET`, and `ANTHROPIC_API_KEY`.
`.env` is gitignored.

### 4. Authorize Yahoo (once)

```bash
.venv/bin/python -m scripts.authorize
```

Your browser will fail to load `https://localhost:8000/callback` — **that's expected**,
nothing is serving it. The authorization code is in the address bar as `?code=...`.
Copy it and paste it into the terminal. The refresh token is saved and renews itself
from then on.

### 5. Run

**Manual mode — the default path for this league:**

```bash
MANUAL_MODE=1 .venv/bin/python -m uvicorn src.server:app --host 0.0.0.0 --port 8000
```

Yahoo denies Fantasy Sports API scope to newly created apps (see *Yahoo API access*
below), so there is no live pick feed. You type picks as they're announced and every
downstream feature works identically.

Entry is built for speed: a surname or a few letters is enough (`gibbs` → Jahmyr
Gibbs). **Enter** marks "someone else took"; the blue button marks it as yours.
Ambiguous input lists the matches rather than guessing — `williams` returns all four.
**Undo last** fixes typos.

**If Yahoo access is ever approved**, drop `MANUAL_MODE=1` and it polls automatically:

```bash
.venv/bin/python -m uvicorn src.server:app --host 0.0.0.0 --port 8000
```

Then open `http://<mac-mini-tailscale-name>:8000` on the iPad.

`--host 0.0.0.0` is what lets the iPad reach it. **Don't port-forward this to the open
internet** — there's no authentication on it. Tailscale keeps it on a private mesh,
which is the entire reason we chose Tailscale over a public tunnel.

## Try it without credentials

```bash
MOCK_MODE=1 .venv/bin/python -m uvicorn src.server:app --port 8000
```

Simulates a draft locally so you can exercise the UI and the flow. Recommendations
still require a real `ANTHROPIC_API_KEY`; without one the UI shows an error banner
and everything else keeps working.

## Using it on draft night

1. Open the page on the iPad before the draft starts.
2. When the draft order is drawn, pick your **slot** in Setup.
3. Choose **your Yahoo team** so roster tracking works.
4. Watch. Recommendations recompute automatically as picks come in — the engine only
   spends a model call when you're within 4 picks of your turn, to avoid burning
   latency and tokens on picks that don't concern you.
5. If Yahoo's feed lags and you know someone's gone, use **Mark Drafted** to correct
   the board without waiting for the poll.

## Known gaps — read before draft day

| Gap | Impact | Fix |
|---|---|---|
| **Board is 100 players deep** | Covers cleanly through ~pick 10 in a 10-team draft. Picks 11-15 have no ranked data. | Extend from Yahoo's player list, or drop in a FantasyPros CSV. See `data/PROVENANCE.md`. |
| **14 of 32 bye weeks missing** | Minor — bye conflicts may be missed. | Yahoo's API returns byes; backfill from there. |
| **Ranks 25-100 are single-source** | Bleacher Report only. Any one outlet has idiosyncratic takes. | Blend a second full source. |
| **Tiers are derived, not sourced** | They're my construction. Most opinionated part of the board. | Sanity-check them yourself. |
| **Model call is untested** | Built and wired, never executed — no API key was available during development. | Run a mock draft with a real key well before draft day. |
| **Draft Type still reads "Offline Draft"** | **If it stays that way, Yahoo hosts no draft room and nobody can join.** | Commissioner must schedule the 2026 draft so it flips to Live Standard Draft. |
| **Yahoo API scope denied** | No live pick feed — manual entry required. | Apply at sports.yahoo.com/developer/access — see `docs/yahoo_api_application.md`. No published timeline. |

## Yahoo API access

OAuth works and a valid token is stored, but every fantasy endpoint returns
`oauth_problem="additional_authorization_required"`. This is not a misconfiguration:
Yahoo moved Fantasy Sports API access behind **manual review**, which is why no Fantasy
permission appears in the developer console (the API Permissions list is empty on both
the create and edit forms — confirmed on desktop, not a mobile rendering artifact).

Access is requested at **https://sports.yahoo.com/developer/access/**. Read-only access
is the only kind offered, which is all this tool needs, and personal single-league use
is explicitly eligible. A prepared application is in `docs/yahoo_api_application.md`.

**Yahoo publishes no approval timeline.** Plan on manual mode for draft day and treat
approval as an upgrade if it lands. If approved, the Access and Use Agreement requires
displaying *"Fantasy data provided by Yahoo Fantasy"* with the official logo — that
attribution must be added to `static/index.html` before using live Yahoo data.

## Pre-draft checklist

- [ ] Commissioner has scheduled the draft; Draft Type reads **Live Standard Draft**
- [ ] Yahoo app registered, `.env` filled in, `scripts/authorize.py` run successfully
- [ ] Mac mini set to **never sleep**; Tailscale running and set to start at login
- [ ] iPad tested against the Tailscale address **from a different network** (cellular
      hotspot), not just from home — this is the step people skip and regret
- [ ] Full dry run against a Yahoo **mock draft** with a real API key
- [ ] Board extended past 100 if you intend to use it beyond ~pick 10

## Layout

```
data/
  rankings.json         Standard-scoring board, 100 deep, tiered
  league_settings.json  Scoring, roster, playoff structure, derived strategy
  PROVENANCE.md         Sources, what was rejected and why, known gaps
src/
  config.py             Env + data loading
  yahoo_auth.py         OAuth2, token refresh
  yahoo_client.py       Yahoo API (its JSON is XML in a trench coat; helpers absorb that)
  draft_state.py        Snake math, roster tracking, need-weighted candidate pool
  recommend.py          Claude Opus 5 engine, cached prefix + structured output
  server.py             FastAPI, background poller, iPad UI
static/index.html       The iPad interface
scripts/authorize.py    One-time Yahoo authorization
```

## Cost

With prompt caching, roughly **$2-3 for an entire draft**. The system prompt and the
full board sit in the cached prefix; each call only pays full price for the small
state delta plus the output.
