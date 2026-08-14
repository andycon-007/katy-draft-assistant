"""Yahoo Fantasy Sports API client.

Yahoo's JSON is genuinely awkward — it is XML transliterated into JSON, so
collections arrive as dicts keyed by stringified integers with a "count" sibling,
and object attributes arrive as a list of single-key dicts. The _flatten and
_iter_collection helpers absorb that so the rest of the codebase sees plain data.
"""

from __future__ import annotations

from typing import Any, Iterator

import httpx

from .config import Settings
from .yahoo_auth import get_valid_access_token

BASE_URL = "https://fantasysports.yahooapis.com/fantasy/v2"


class YahooClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._game_key: str | None = None

    # ------------------------------------------------------------------ core

    def _get(self, path: str) -> dict:
        token = get_valid_access_token(self.settings)
        url = f"{BASE_URL}/{path.lstrip('/')}"
        sep = "&" if "?" in url else "?"
        resp = httpx.get(
            f"{url}{sep}format=json",
            headers={"Authorization": f"Bearer {token}"},
            timeout=20.0,
        )
        resp.raise_for_status()
        return resp.json()

    # -------------------------------------------------------------- helpers

    @staticmethod
    def _flatten(obj: Any) -> dict:
        """Yahoo represents an object as a list of single-key dicts. Merge them."""
        if isinstance(obj, dict):
            return obj
        merged: dict = {}
        if isinstance(obj, list):
            for part in obj:
                if isinstance(part, dict):
                    merged.update(part)
                elif isinstance(part, list):
                    merged.update(YahooClient._flatten(part))
        return merged

    @staticmethod
    def _iter_collection(node: Any) -> Iterator[Any]:
        """Yield members of a Yahoo collection dict keyed by '0','1',... plus 'count'."""
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            if key == "count":
                continue
            if not key.isdigit():
                continue
            yield value

    # ----------------------------------------------------------------- game

    @property
    def game_key(self) -> str:
        """Current NFL game key. Yahoo accepts the literal 'nfl' for the active season."""
        if self._game_key is None:
            try:
                data = self._get("game/nfl")
                game = self._flatten(data["fantasy_content"]["game"])
                self._game_key = str(game.get("game_key", "nfl"))
            except Exception:
                # 'nfl' resolves to the current season server-side, so this is a safe default.
                self._game_key = "nfl"
        return self._game_key

    @property
    def league_key(self) -> str:
        return f"{self.game_key}.l.{self.settings.league_id}"

    # --------------------------------------------------------------- league

    def league_settings(self) -> dict:
        data = self._get(f"league/{self.league_key}/settings")
        league = data["fantasy_content"]["league"]
        return self._flatten(league)

    def league_metadata(self) -> dict:
        data = self._get(f"league/{self.league_key}")
        return self._flatten(data["fantasy_content"]["league"])

    def teams(self) -> list[dict]:
        data = self._get(f"league/{self.league_key}/teams")
        league = data["fantasy_content"]["league"]
        container = league[1]["teams"] if isinstance(league, list) else league["teams"]
        out = []
        for member in self._iter_collection(container):
            team = self._flatten(member.get("team", member))
            out.append(team)
        return out

    # ---------------------------------------------------------- draft state

    def draft_results(self) -> list[dict]:
        """Pick-by-pick draft results.

        Populates in real time during a LIVE draft. Returns an empty list before
        the draft starts, and stays empty for an offline draft until the
        commissioner enters results manually.
        """
        data = self._get(f"league/{self.league_key}/draftresults")
        league = data["fantasy_content"]["league"]
        container = (
            league[1]["draft_results"]
            if isinstance(league, list)
            else league.get("draft_results", {})
        )
        picks = []
        for member in self._iter_collection(container):
            result = self._flatten(member.get("draft_result", member))
            if not result:
                continue
            picks.append(
                {
                    "pick": int(result.get("pick", 0)),
                    "round": int(result.get("round", 0)),
                    "team_key": result.get("team_key", ""),
                    "player_key": result.get("player_key", ""),
                }
            )
        picks.sort(key=lambda p: p["pick"])
        return picks

    # -------------------------------------------------------------- players

    def players(self, start: int = 0, count: int = 25, status: str | None = None) -> list[dict]:
        """A page of players, Yahoo-ranked. `status='A'` filters to available."""
        path = f"league/{self.league_key}/players;start={start};count={count}"
        if status:
            path += f";status={status}"
        data = self._get(path)
        league = data["fantasy_content"]["league"]
        container = league[1]["players"] if isinstance(league, list) else league.get("players", {})
        out = []
        for member in self._iter_collection(container):
            raw = member.get("player", member)
            player = self._flatten(raw[0] if isinstance(raw, list) and raw else raw)
            name = player.get("name", {})
            out.append(
                {
                    "player_key": player.get("player_key", ""),
                    "player_id": player.get("player_id", ""),
                    "name": name.get("full", "") if isinstance(name, dict) else str(name),
                    "position": player.get("display_position", ""),
                    "team": player.get("editorial_team_abbr", ""),
                    "bye": self._extract_bye(player),
                    "status": player.get("status", ""),
                }
            )
        return out

    @staticmethod
    def _extract_bye(player: dict) -> int | None:
        weeks = player.get("bye_weeks")
        if isinstance(weeks, dict):
            week = weeks.get("week")
            if week:
                try:
                    return int(week)
                except (TypeError, ValueError):
                    return None
        return None

    def all_players(self, limit: int = 300) -> list[dict]:
        """Walk the paginated player list. Yahoo caps each page at 25."""
        collected: list[dict] = []
        start = 0
        while start < limit:
            page = self.players(start=start, count=25)
            if not page:
                break
            collected.extend(page)
            start += 25
        return collected[:limit]
