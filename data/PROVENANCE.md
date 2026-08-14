# Rankings Board — Provenance & Gaps

Built 2026-08-14. Read this before trusting the board on draft day.

## What was actually extracted

| Source | What I got | Usable? |
|---|---|---|
| [Bleacher Report Top 100 PPR](https://bleacherreport.com/articles/25458550-top-100-fantasy-football-rankings-ppr-leagues-2026) | **Full ordered top 100** | Yes — this is the backbone of the board |
| [FanDuel Top 150 PPR](https://www.fanduel.com/research/fantasy-rankings-top-150-ppr-rankings-for-2026-fantasy-football) | Top 7 + tier commentary | Partial — used to corroborate the elite tier |
| [PFF PPR Top 100](https://www.pff.com/news/fantasy-football-rankings-ppr-top-100) | Top 3 | Partial — corroboration only |
| [nflfantasyedge 2026](https://nflfantasyedge.com/rankings-2026/) | Elite tier + PPR/Half/Standard shift notes | Partial — source of the format-sensitivity notes |
| [DraftSharks PPR](https://www.draftsharks.com/rankings/ppr) | Team bye weeks for 18 teams | Partial — names were obfuscated, byes were not |
| [fftoolbox ADP](https://fftoolbox.fulltimefantasy.com/football/adp.cfm) | Top 50 ADP, updated 2026-08-13 | **Rejected — see below** |

## Why the fftoolbox ADP was excluded

It lists 11 QBs inside the top 51, with Josh Allen at 3.62 overall. That is a **superflex / 2-QB** draft pattern, not a 1-QB league. Blending it into a 1-QB board would have pushed every quarterback 20-40 picks too high — the single most damaging error this board could contain. It was used only to cross-check player names and team assignments.

This is worth remembering as a general rule: unlabeled ADP data on the open web is frequently superflex.

## Known gaps

1. **Only 100 players deep.** A 12-team, 16-round draft is ~192 picks. This board covers roughly rounds 1-8 for a 12-team league. The late rounds (kickers, defenses, lottery tickets) are uncovered.
2. **14 of 32 bye weeks are null.** Backfill from the Yahoo API, which returns them reliably — this is not worth solving by scraping.
3. **Tiers are derived, not sourced.** I constructed the tier boundaries from the consensus ordering. They are the most opinionated part of this file and the first thing to sanity-check.
4. **Single-source ordering below the top ~20.** Ranks 25-100 rest almost entirely on Bleacher Report. Any single outlet has idiosyncratic takes; BR's Smith-Njigba at #2 is a visible example.
5. **No kickers or defenses at all.**

## Why scraping stalled

Nearly every modern fantasy site (FantasyPros, ESPN, Yahoo, RotoBaller, DraftSharks) renders rankings client-side via JavaScript. `WebFetch` retrieves the HTML shell — navigation and headers — but not the table. Bleacher Report and fftoolbox were the exceptions.

**Closing the gap does not require better scraping.** Two better paths:

- **Yahoo API (preferred).** Once OAuth is set up, Yahoo returns its own full player list with ranks, positions, bye weeks, and injury status — for *your actual league's scoring settings*. That is strictly better than any scraped consensus board, and it eliminates gaps 1, 2, and 5 at once.
- **Manual export.** FantasyPros allows a CSV download of consensus rankings with a free account. One download, dropped in this directory, closes the depth gap immediately.

## Recommended next step

Do the Yahoo OAuth setup before investing further in this file. The API supersedes most of what is missing here, and it resolves the open question about the league's scoring format — which determines whether this PPR-based ordering is even the right basis.

## Sources

- [Bleacher Report — Top 100 Fantasy Football Rankings for PPR Leagues in 2026](https://bleacherreport.com/articles/25458550-top-100-fantasy-football-rankings-ppr-leagues-2026)
- [FanDuel Research — Top 150 PPR Rankings for 2026](https://www.fanduel.com/research/fantasy-rankings-top-150-ppr-rankings-for-2026-fantasy-football)
- [PFF — 2026 Fantasy Football Rankings: PPR Top 100](https://www.pff.com/news/fantasy-football-rankings-ppr-top-100)
- [nflfantasyedge — 2026 Fantasy Football Rankings](https://nflfantasyedge.com/rankings-2026/)
- [DraftSharks — Fantasy Football PPR Rankings 2026](https://www.draftsharks.com/rankings/ppr)
- [fftoolbox — 2026 Fantasy Football ADP](https://fftoolbox.fulltimefantasy.com/football/adp.cfm) *(excluded — superflex)*
