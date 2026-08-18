# Yahoo Fantasy Sports API — Access Application

Submit at **https://sports.yahoo.com/developer/access/**

Yahoo warns that *"incomplete or insufficiently detailed submissions cannot be
evaluated and will be closed without further correspondence."* So this is written to
be specific and concrete rather than generic. Being plainly a small personal project
is an advantage here, not something to disguise — the form explicitly accommodates
personal and single-league use.

---

## Field values

**Client ID** — copy from your local `.env` (`YAHOO_CLIENT_ID`), or from
developer.yahoo.com/apps. Deliberately not recorded here, since this file is public.

**Estimated number of users:** Small (fewer than 1,000) — realistically **1**

**Access type:** Read-only

---

## What are you building?

> A personal draft-assistant tool for a single Yahoo Fantasy Football league I play in
> (league #878541, 10 teams, standard non-PPR scoring).
>
> During my league's live draft I want a second screen that shows which players are
> still available, tracks my own roster construction against the league's starting
> requirements, and suggests my next pick. My league uses standard scoring rather than
> PPR, which most published rankings assume, so the tool reweights a rankings board for
> our actual scoring settings and factors in roster need.
>
> It runs on a single machine on my home network and is viewed from my iPad. There is
> no public deployment, no hosted service, no user accounts, and nobody else uses it.

## What Yahoo Fantasy Sports data do you need?

> Three read-only endpoints, all scoped to the one league I am a member of:
>
> 1. **League settings** (`/league/{key}/settings`) — to read our scoring rules and
>    roster positions rather than requiring me to hand-enter them, which is error-prone.
> 2. **Draft results** (`/league/{key}/draftresults`) — to know which players have been
>    taken as the live draft progresses, so available-player suggestions stay accurate.
> 3. **League players** (`/league/{key}/players`) — for the player list with positions,
>    NFL teams, bye weeks, and injury status.
>
> I also read `/league/{key}/teams` once, to identify which team is mine so I can track
> my own roster.
>
> I do not need write access. The tool only observes the draft; I make my own picks in
> the Yahoo draft room.

## Who are your intended users and what is the access scope?

> Just me. This is a personal single-league project with no other users and no plans to
> distribute it. The scope is one league for one season. If it is useful I will keep
> using it in future seasons of the same league.

## Additional notes

> Polling frequency would be roughly once every 8 seconds, and only during the ~90
> minutes of our live draft — not continuously through the season. Happy to reduce that
> or add caching if the rate is a concern.
>
> I understand access is read-only and I have no need for write access.
>
> If approved I will display the required "Fantasy data provided by Yahoo Fantasy"
> attribution with a link to Yahoo Fantasy and the official logo.

---

## If approved — what we owe Yahoo

Per the API Access and Use Agreement:

- [ ] Display **"Fantasy data provided by Yahoo Fantasy"** in the UI, linking to Yahoo Fantasy
- [ ] Use the official Yahoo Fantasy logo, correctly
- [ ] Stay within reasonable request volume (our 8s poll during a single draft is modest)
- [ ] No reverse-engineering, no multiple accounts

The attribution is a real requirement, not boilerplate — it needs adding to
`static/index.html` before the tool is used against live Yahoo data.

## Timeline risk

Yahoo publishes **no approval timeline**, and review is done by a human team. With a
draft coming up in weeks, approval may or may not land in time.

**This does not block draft day.** The tool runs in `MANUAL_MODE` — you enter picks as
they're announced and every downstream feature (recommendations, roster tracking,
need-weighting, tier awareness) works identically. Yahoo access would remove the typing,
not enable the intelligence.

Apply now, plan on manual mode, and treat approval as an upgrade if it arrives.
